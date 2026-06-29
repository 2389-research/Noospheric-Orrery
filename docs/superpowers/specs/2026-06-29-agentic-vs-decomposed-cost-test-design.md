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

### Cost & artifact capture

- **Agentic cost:** `refine()` returns `total_usage` (the SDK `UsageTracker`: tokens by model/role +
  cost). The old code discarded it; the restored module **captures `golden_result.total_usage` and
  `spec_result.total_usage`** and writes them to the arm's `cost.json`. This is the *only* additive
  change to the restored code and does not alter how agents are invoked or prompted.
- **Decomposed cost:** the runner monkeypatches `Relay.from_settings` to attach an `on_usage`
  callback (orrery-relay already emits `UsageEvent` with `input_tokens`/`output_tokens` per call),
  feeding the **same** SDK `UsageTracker` + `PRICING` table. One cost model prices both arms.
- **Artifacts saved per arm:** the golden set, final spec, every `iteration-N-judgment.md`, the
  `eval-N/` extraction-result dirs (Phase 2), the `simmer_iterations` + `simmer_criterion_details`
  rows (in the arm's DB copy), and `cost.json`.

### Cost basis (fairness)

Both arms are priced from **token counts via the same SDK `PRICING` table** — this is the
apples-to-apples number. On bedrock the agentic CLI may also report `total_cost_usd`; when present we
record it as a **secondary cross-check** only, never as the primary comparison metric (mixing
CLI-reported and estimated costs across arms would not be comparable).

## Metrics reported

Per arm, per phase (golden / spec) and total:
- input tokens, output tokens, total tokens
- estimated cost (USD) from the shared `PRICING` table
- API-call count
- wall-clock seconds

Then a **qualitative read** (by Claude, reading the artifacts) of both goldens and both specs:
coverage, precision, taxonomy/type quality, generalizability, and obvious failure modes — *not*
exact-match F1 (too brittle: a valid entity with a different type reads as a miss).

## Default scope

- Domain: `business/venture_capital/vc_firms` (26 chunks / 11 docs).
- Pinned to **10 chunks**; **seed + 2 iterations** both arms.
- Alternative smaller domain if preferred: `hobby/miniature_painting/techniques` (16 chunks / 2 docs).

## Components

| Unit | Responsibility | Committed? |
|------|----------------|-----------|
| `worker/src/jobs/simmer_general_agentic.py` | old agentic general flow, restored verbatim from `58498de` + `total_usage` capture | **no** (experiment scratch) |
| `worker/src/jobs/simmer_domain_agentic.py` | old agentic domain flow, restored verbatim from `58498de` + `total_usage` capture | **no** |
| experiment runner (e.g. `scripts/cost_bakeoff.py`) | pin DB copy, set isolated env, run both arms, attach relay `on_usage`, dump `cost.json` + metrics manifest | **no** |
| `docs/.../2026-06-29-agentic-vs-decomposed-cost-test.md` | methodology: exact commands, what's measured, how to reproduce, the results table + qualitative findings | **yes** |

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

## Open questions (resolved)

- **O1 — same models both arms?** Resolved: the live `.env` already runs Sonnet 4.6 + Haiku 4.5, the
  same pairing the old flow hardcoded. No tuning needed; cost delta is pure architecture.
- **O2 — how to get cost out of the agentic flow that bypasses orrery-relay?** Resolved:
  `refine().total_usage` (SDK `UsageTracker`) reports it natively.
- **O3 — does the old code still run against today's SDK/schema/config?** Resolved: verified yes;
  zero drift in every dependency it touches.
