# Agentic vs decomposed simmer — cost / time / quality

**Date:** 2026-06-29 · **Status:** Complete, n=1 (one domain, one run per arm — directional) · **Branch:** `experiment/agentic-vs-decomposed-cost`

This README is the record. Full detail in the two companion docs:
- [`design.md`](./design.md) — method, cost-capture mechanism, phase-0 spike
- [`findings.md`](./findings.md) — full results + grounded quality read

## Question

On Claude, is the old **agentic `refine()`** simmer worth its cost vs the shipped
**decomposed** flow (built for local models), on the same real domain simmer?

## Setup

- **Base commit (shared code state):** `3671254` (head of `main` at the time).
- **Arms:**
  - *Agentic* — pre-decomposition `run_simmer_domain` restored verbatim from
    commit **`58498de`** (two `simmer_sdk.refine()` calls, board judging, tool-using
    agent reads chunks). Today's SDK runs that same strategy via a direct-API
    tool-use loop (`api_agent.run_api_agent`), not the original `ClaudeSDKClient`
    CLI subprocess (CLI path was removed from the SDK). Strategy identical; only
    transport differs.
  - *Decomposed* — the shipped `run_simmer_domain` (bounded `relay.complete`
    calls, single relay judge at the inert `JUDGE_COUNT=1/JUDGE_SAMPLES=1` default).
- **Params:** domain `business/venture_capital/vc_firms`; DB copy trimmed to the
  **same pinned 10 chunks** (so the old `ORDER BY RANDOM() LIMIT 10` is
  deterministic); seed + 2 iterations; **Sonnet 4.6 + Haiku 4.5**; **bedrock**.
- **Cost mechanism (one, shared):** both arms record accurate per-call tokens into
  a `simmer_sdk.usage.UsageTracker`, priced by the same `PRICING` table (Sonnet
  $3/$15, Haiku $0.8/$4 per Mtok). No `total_cost_usd` bridge / undercount.
- **Artifacts (NOT in this repo):**
  [`DS-scratch/noospheric_agentic_vs_decomposed_simmer/`](https://github.com/2389-research/DS-scratch/tree/main/noospheric_agentic_vs_decomposed_simmer)
  — the resurrected agentic module + notes. The raw `cost.json`, per-run
  goldens/specs, and the `bakeoff_*.py` runners were ephemeral scratchpad and did
  not survive a machine restart; they are regenerable from the module + this setup.

## How to run

Experiment code is scratch, kept in DS-scratch (not here). Reproduction outline:

1. Restore the agentic module (`simmer_domain_agentic.py`) and the two runners.
2. Copy `~/orrery-data/orrery.db`, trim it to the pinned 10 `vc_firms` chunks,
   point `SPECS_DIR` at an isolated temp dir.
3. Run each arm via `worker/.venv/bin/python` (resolves the **usage-capable**
   editable `simmer-sdk`; the vendored `worker/simmer-sdk/` Docker copy has no
   usage tracking — do **not** use it). The decomposed runner monkeypatches
   `Relay.from_settings` to attach an `on_usage` hook → `UsageTracker`.
4. Quality: have an LLM read both arms' goldens + specs against the 10 source
   chunks (exact-match F1 is too brittle).

## Results

| Metric | Agentic | Decomposed | Ratio |
|---|---|---|---|
| Cost (USD) | $12.58 | $0.46 | **~27× cheaper** |
| Total tokens | 3.80M | 0.15M | ~26× fewer |
| API calls | 190 | 51 | ~3.7× fewer |
| Wall-clock | ~20.4 min | ~5.4 min | ~3.8× faster |

- **Why so lopsided:** the agentic arm is input-token-bound (3.70M in : 0.10M out)
  — the tool-using judge re-sends context + re-reads chunks every turn; **87% of
  its cost was judging.** Decomposed pushes bulk extraction to Haiku (40 calls =
  $0.08) and uses Sonnet only for ~11 judge/generator/type calls.
- **Quality (grounded LLM read):** decomposed is **comparable-to-better**. The
  expensive agentic spec **overfit** — it hardcoded corpus-specific names into its
  rules (e.g. `notes.granola.so ⇒ extract granola`), which fail on unseen docs;
  the decomposed spec states transferable rules and forbids hardcoding. Decomposed
  also kept VC-first-class types and the load-bearing deal terms; agentic flattened
  them to generic Person/Organization and stripped dollar amounts. Decomposed's only
  real loss: a noisier `competitor` type (4 bad calls) + a couple misses — fixable
  with a one-line EXCLUDE tweak.

## Conclusion

The decomposition built out of necessity for local models is the **better default
on Claude too** — not a compromise. The agentic flow's expense bought overfitting,
not quality.

## Caveats

- **n=1** — one domain, one run per arm. Directional, not significant.
- One domain TYPE (`vc_firms`); taxonomy-heavy domains may differ (see the
  multi-judge-board validation findings).
- Agentic arm used the SDK's current direct-API tool-loop, not the original CLI
  subprocess (strategy identical).
- Quality is one LLM's grounded read, not a hand-checked gold standard.

## Follow-ups

- Tighten the decomposed spec's `competitor` EXCLUDE rule (the one real quality loss).
- More domains / repeated runs for significance.
- The agentic-arm source is also recoverable at tag `exp/pre-decomposition-simmer` (→ `58498de`).
