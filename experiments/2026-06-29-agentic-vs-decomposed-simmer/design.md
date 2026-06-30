# Agentic vs Decomposed Simmer — Cost / Time / Quality Bake-off

**Date:** 2026-06-29
**Branch:** `experiment/agentic-vs-decomposed-cost`
**Status:** Design (approved for setup)

## Goal

Measure what the **agentic** simmer architecture actually costs versus the **decomposed**
(non-agentic) one, on Claude, by running **both flows on the same simmer task** — same domain,
same input chunks, same models, same backend — and capturing token cost, wall-clock time, and the
qualitative outputs (golden set + extraction spec).

This answers a question the codebase implicitly assumed but never measured: when the text simmer was
decomposed for local models (gemma4) on 2026-06-23, the capable-but-costly agentic `refine()` path
was **deleted outright, not gated on backend**. So today even Claude runs through the decomposed
flow. Was that trade worth it for Claude — how much cheaper/faster is decomposed, and how much (if
any) quality do we give up?

## Background — the two flows

- **Decomposed (current, shipped):** `worker/src/jobs/simmer_general.py` / `simmer_domain.py`.
  Every LLM touch is a single bounded `relay.complete` / `complete_structured` (no tools, no
  multi-turn agent, `think:false`). Generate → evaluate (deterministic F1) → judge (one relay call,
  `build_judge_prompt`) → reflect. This is "the local model flow."
- **Agentic (deleted 2026-06-23, last present at `58498de`):** the original
  `run_simmer_general` / `run_simmer_domain` made **two `simmer_sdk.refine()` calls** (golden +
  spec), each an agentic `ClaudeSDKClient` loop with `judge_mode="board"`, tool-driven file reading
  (`background=` tells the agent to read the sample docs), Sonnet generator+judge, Haiku clerk.

Today the **only** surviving agentic `refine()` call in the product is the image simmer
(`simmer_domain_image.py:176`) — confirming the agentic text path is gone, not hidden behind a flag.

## Why Approach A (resurrect verbatim, run in current env)

We considered: **(A)** restore the old function bodies and run them in today's environment, vs
**(B)** check out the old worker at `58498de` in a git worktree and run it as-is.

Verification (done 2026-06-29) shows **everything the old flow depends on still exists today**, so A
has no fidelity cost and avoids B's drift risk:

- `worker/src/jobs/evaluate_spec.py` (Phase-2 evaluator) — present.
- Config fields read by the old flow — all present: `anthropic_backend`, `aws_access_key`,
  `aws_secret_key`, `aws_region`, `classification_model`, `simmer_iterations`, `specs_dir`,
  `ollama_url`.
- Every table/column the old flow writes — present with matching columns: `simmer_iterations`,
  `simmer_criterion_details`, `specs`, `jobs`, `domains.spec_version`, and the read tables
  (`documents`, `chunks`, `document_domains`).
- The `refine()` signature the old flow uses (`judge_panel`, `generator_model`/`judge_model`/
  `clerk_model`, `judge_mode="board"`, `background`, `output_dir`, `evaluator`, `on_iteration`,
  `**provider_kwargs`) is **identical** to what the live image simmer calls today → the current SDK
  accepts it unchanged.

**Fidelity bar (the explicit requirement): the agentic arm must do the work exactly as the old flow
did** — same `refine()` invocations, same criteria, same `judge_panel` lenses, same `background`
prompts, same models, same `output_dir` artifact writing, same `on_iteration` DB persistence, same
queued `extract_batch`. We restore the full function bodies from `58498de`, not a hand-picked subset.

## Architecture

### Arms

| Arm | Code | How it runs |
|-----|------|-------------|
| **agentic** | `simmer_*_agentic.py` restored verbatim from `58498de` | the two `refine()` calls, byte-for-byte prompts/criteria/models |
| **decomposed** | the real shipped `run_simmer_domain` | unchanged |

Both arms run on the **same pinned DB copy**, the **same domain**, the **same models**
(Sonnet 4.6 judge/generator, Haiku 4.5 clerk/extract — already the live `.env`), **bedrock** backend.

### Holding inputs constant (architecture = only variable)

1. **Copy the live DB** to a per-run scratch path; never touch `~/orrery-data/orrery.db`.
2. **Pin the chunk pool:** delete all but exactly **N** chunks for the target domain in the copy, so
   the old flow's `... ORDER BY RANDOM() LIMIT 10` returns the same N for both arms. This requires
   **no edit to the old query** — the pool simply *is* those N. (Same `build_pinned_base` trick as
   `scripts/domain_judge_experiment.py`.) N ≤ 10 so it satisfies both arms' `LIMIT`.
3. **Isolated `SPECS_DIR` + `DB_PATH` per arm** via env, so artifacts/specs don't collide.
4. **Precondition check:** detect whether a general spec row (`specs.domain_path IS NULL`) exists.
   The old domain flow seeds Phase 1 from it when present, else uses a generic fallback seed. The
   runner records which seed condition applied so both arms are interpreted against the same starting
   state. (We do **not** force the two flows to match internal steps — decomposed legitimately does
   domain-type discovery + additive golden; that architectural difference is the thing under test.
   We hold only the *external* inputs constant.)

### SDK pinning (prerequisite — there are multiple `simmer-sdk` copies on disk)

Usage capture depends on which `simmer_sdk` is imported. Verified 2026-06-29:
- `worker/.venv/bin/python` resolves `simmer_sdk` to the **editable install at
  `~/Documents/GitHub/simmer-sdk/`**, which **has** `usage.py` (`UsageTracker`, `PRICING`) and a
  `SimmerResult.usage` field. On the **bedrock/API providers this SDK runs the agentic loop via
  `api_agent.run_api_agent`** (a direct Messages-API tool-use loop, `max_turns=25`, Read/Grep/Glob
  tools) — *not* the legacy `ClaudeSDKClient` subprocess — and records **accurate per-call** usage via
  `UsageTracker.record(...)` (api_agent.py:110-111) for every turn. Wired in `refine.py:418`.
- The **vendored** `worker/simmer-sdk/` copy (used only for the Docker build) is an **older version
  with no usage tracking**. The experiment must NOT run against it.

**Transport note (fidelity, user-approved 2026-06-29):** the original old flow (`58498de`) ran its
agentic loop through the `ClaudeSDKClient` CLI subprocess; the current SDK runs the *identical
agentic strategy* (same prompts, criteria, models, judge panels, `background`, tool-use) through the
direct-API loop instead — the CLI path was removed from the SDK and is not configurable. The agent
makes the same decisions and tool calls; only the transport differs. This is accepted as faithful
(and is strictly better for metering: accurate per-call tokens, no subprocess overhead).

The experiment runs via `worker/.venv/bin/python`. The runner **asserts at startup** that the
imported SDK exposes usage — `hasattr(SimmerResult, '__dataclass_fields__') and 'usage' in
SimmerResult.__dataclass_fields__`, and that `simmer_sdk.usage` imports — and **fails fast** with a
clear message otherwise. (O3-style runtime grounding, not an assumption.)

### Cost & artifact capture

- **Agentic cost:** each `refine()` returns a `SimmerResult` with a **`usage`** field (a
  `UsageTracker`; `.to_dict()` → `total_input_tokens`, `total_output_tokens`, `estimated_cost_usd`,
  `by_role`, `by_model`). The old code discarded it; the restored module **captures
  `golden_result.usage` and `spec_result.usage`** and writes them to the arm's `cost.json`. This is
  the *only* additive change to the restored code and does not alter how agents are invoked/prompted.
  On bedrock the direct-API agent loop records **every turn** via `UsageTracker.record(...)`, so the
  agentic arm's per-call token counts are **accurate and complete** — verified by the Phase 0 spike.
- **Decomposed cost:** the runner monkeypatches `Relay.from_settings` to attach an `on_usage`
  callback (orrery-relay emits `UsageEvent` with `input_tokens`/`output_tokens` for **every** bounded
  call), feeding a runner-owned `UsageTracker`. Decomposed token counts are also **exact**.
- **Artifacts saved per arm:** the golden set, final spec, every `iteration-N-judgment.md`, the
  `eval-N/` extraction-result dirs (Phase 2), the `simmer_iterations` + `simmer_criterion_details`
  rows (in the arm's DB copy), and `cost.json` (raw `usage.to_dict()` for each phase).

### Cost basis (fairness) — one mechanism, token-based

**Both arms are metered the same way:** accurate per-call `(input_tokens, output_tokens)` →
accumulated in a `UsageTracker` → priced by the **same** `simmer_sdk.usage.PRICING` table
(Sonnet 4.6 = $3/$15 per Mtok; Haiku 4.5 = $0.8/$4; friendly + `us.anthropic.*` ids). This is a
single, identical cost mechanism — not a bridge between two different sources:

- **Agentic arm:** the SDK's direct-API loop records each turn via `record()` (accurate per-call
  tokens). `result.usage` already prices it via `PRICING`.
- **Decomposed arm:** orrery-relay `on_usage` records each bounded call (accurate per-call tokens),
  priced via the same `PRICING` import.

So **tokens AND derived USD are both fair comparison axes** for this experiment. (Historical note: a
*different* execution path — the legacy `ClaudeSDKClient` CLI subprocess — recorded only final-turn
tokens and relied on `total_cost_usd`; that path is not used here. The bedrock direct-API loop avoids
it entirely, which is why the unified token mechanism is valid. This was the open risk in earlier
drafts; the Phase 0 spike resolved it.)

## Metrics reported

Per arm, per phase (golden / spec) and total:
- input / output / total tokens (accurate per-call for both arms)
- estimated cost (USD) — same `PRICING` table for both arms
- API-call count (the agentic vs decomposed call-count gap is itself a headline result — the spike
  showed 19 calls for a trivial 1-doc/1-iter/1-judge golden)
- wall-clock seconds

Then a **qualitative read** (by Claude, reading the artifacts) of both goldens and both specs:
coverage, precision, taxonomy/type quality, generalizability, and obvious failure modes — *not*
exact-match F1 (too brittle: a valid entity with a different type reads as a miss).

## Phase 0 — cost-source spike — ✅ DONE (2026-06-29)

A minimal 1-iteration agentic `refine()` on bedrock (Sonnet+Haiku, 1 doc, 1-judge board) confirmed:
- `simmer_sdk` resolves to the usage-capable editable install; `SimmerResult.usage` present.
- The agentic loop runs via the **direct-API tool-use path** and records **accurate per-call tokens**
  for every turn (`record()`), not the final-turn-only `record_agent` undercount — so the unified
  token-based cost mechanism is valid on bedrock.
- Result: golden composite **9.5**, **19 calls, 91,219 tokens, $0.288** for a trivial input —
  by-role/by-model breakdown captured. (`_agent_cost` was `None` on every call, which is *expected
  and fine*: the direct-API path doesn't use `total_cost_usd`; per-call tokens are the accurate source.)

Conclusion: bedrock is a valid backend for a fair token-based comparison; no need to fall back to
gateway/`total_cost_usd`. Spike artifacts are scratch (uncommitted).

## Default scope

- Domain: `business/venture_capital/vc_firms` (26 chunks / 11 docs).
- Pinned to **10 chunks**; **seed + 2 iterations** both arms.
- Alternative smaller domain if preferred: `hobby/miniature_painting/techniques` (16 chunks / 2 docs).

## Components

| Unit | Responsibility | Committed? |
|------|----------------|-----------|
| `worker/src/jobs/simmer_general_agentic.py` | old agentic general flow, restored verbatim from `58498de` + `result.usage` capture | **no** (experiment scratch) |
| `worker/src/jobs/simmer_domain_agentic.py` | old agentic domain flow, restored verbatim from `58498de` + `result.usage` capture | **no** |
| experiment runner (e.g. `scripts/cost_bakeoff.py`) | pin DB copy, set isolated env, run both arms, attach relay `on_usage`, dump `cost.json` + metrics manifest | **no** |
| `findings.md` (same dir) | methodology: exact commands, what's measured, how to reproduce, the results table + qualitative findings | **yes** |

## What is and isn't committed

- **Committed:** this design doc and the final methodology/findings doc.
- **Not committed:** the resurrected agentic modules, the runner, and all raw run artifacts. They are
  experiment scratch — useful to keep locally, not part of the shipped product. (Per the explicit
  decision that "odds are we won't commit the actual experiments, but it's good for us to know.")

## Error handling

- Per-arm isolation: if one arm errors, capture the traceback to its `summary.json`, still attempt to
  dump whatever artifacts/usage exist, and continue to the other arm.
- DB copy + scratch `SPECS_DIR` guarantee the live data is never mutated, even on crash.
- If the pinned domain has fewer than N valid-status chunks, fail fast with a clear message rather
  than running on a different sample than intended.

## Open questions

- **O1 — same models both arms?** Resolved: the live `.env` already runs Sonnet 4.6 + Haiku 4.5, the
  same pairing the old flow hardcoded. No tuning needed; cost delta is pure architecture.
- **O2 — how to get accurate cost out of the agentic flow that bypasses orrery-relay?** **Resolved
  (Phase 0 spike, 2026-06-29).** On bedrock the SDK runs the agentic loop via the direct-API tool-use
  path, which records **accurate per-call tokens** for every turn (`UsageTracker.record`). So both
  arms use **one identical token-based mechanism** priced by the same `PRICING` table — no
  `total_cost_usd` bridge, no fairness asterisk. (Earlier drafts assumed the legacy `ClaudeSDKClient`
  CLI path with final-turn-only tokens; that path isn't used here. Field is `result.usage`, not
  `total_usage`.)
- **O3 — does the old code still run against today's SDK/schema/config?** Resolved: verified yes;
  zero drift in every dependency it touches. **Caveat:** there are multiple `simmer-sdk` copies on
  disk; usage capture only works against the editable `~/Documents/GitHub/simmer-sdk` that
  `worker/.venv` resolves — the runner asserts this at startup (see "SDK pinning").
