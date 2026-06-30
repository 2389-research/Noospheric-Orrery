# ADR-0001: Use the decomposed simmer loop, not agentic `refine()`

**Status:** Accepted (2026-06-30)
**Deciders:** Nomzor
**Supersedes:** —

## Context

The simmer pipeline refines extraction specs via an RL-style loop
(**generate → evaluate → judge → reflect**, steered by the single highest-leverage
fix, the ASI). There are two ways to drive these stages:

- **Agentic** — simmer-sdk's `refine()` runs each stage as a tool-using
  `ClaudeSDKClient` (now direct-API) loop that reads the corpus on every turn.
- **Decomposed** — every stage is a bounded, non-agentic `relay.complete` call
  (`worker/src/jobs/simmer_core.py`: `simmer_loop` + `relay_judge`), with
  `think:false`. simmer-sdk is reused only for the **judge contract**
  (`build_judge_prompt`, `parse_judge_output`).

The decomposed loop was originally built out of necessity: local models (gemma4)
stall in agentic loops. The open question was whether the agentic flow is
nonetheless worth its cost **on Claude**. Two experiments answered it:

- [Agentic vs decomposed bake-off (2026-06-29)](../../experiments/2026-06-29-agentic-vs-decomposed-simmer/)
  — same domain, same pinned inputs, same models. Decomposed was **~27× cheaper,
  ~3.8× faster, and comparable-to-better quality**; the expensive agentic flow
  **overfit** (hardcoded corpus-specific names into its spec rules). 87% of agentic
  cost was the tool-using judge re-reading context every turn.
- [Multi-judge board gemma4 validation (2026-06-26)](../../experiments/2026-06-26-multi-judge-board-validation/)
  — the decomposed loop with an optional N×K judge board produces a richer,
  better-typed golden at ~2.3× compute, opt-in via inert-by-default knobs.

History also weighs in: PR #27 "simplified" the decomposed loop by deleting the
judge stage entirely and reintroduced documented failures (the #27 regression),
recovered in PRs #29/#31. The stage structure is load-bearing.

## Decision

**The decomposed simmer loop is the default and only shipped flow.** Every stage
runs as a bounded non-agentic relay call. We do **not** call simmer-sdk `refine()`;
we reuse it only for the judge contract. The multi-judge board stays **opt-in**
(`JUDGE_COUNT`/`JUDGE_SAMPLES`/`JUDGE_PANEL`/`JUDGE_DELIBERATE`; default `N=1/K=1`
is byte-for-byte the single relay judge). The simmer invariants in `CLAUDE.md`
(distinct judge stage, ASI-only context discipline, calibrated judge, F1 feeds the
judge, judge prompt built from the simmer-sdk judge skill, reflect retained) MUST
be preserved.

## Consequences

**Positive**
- ~27× cheaper / ~3.8× faster per domain simmer on Claude; one backend-agnostic
  code path works on both local (gemma4) and cloud (Sonnet/Haiku).
- More generalizable specs — bounded single-pass structure avoids the agentic
  flow's corpus-memorization/overfitting.

**Negative / risks**
- We forgo the agentic flow's open-ended tool-use exploration; a future
  taxonomy-heavy domain class could plausibly benefit (the board partly addresses
  this, opt-in).
- Evidence is **n=1** (bake-off) / **n=2** (board) — directional, not significant.
- The stage discipline is fragile to "simplification" — see the #27 regression.
  Enforced by `worker/tests/test_simmer_core.py` and the `CLAUDE.md` warning.

**Revisit if** a future experiment shows the agentic flow winning on a domain class
the decomposed loop handles poorly. Supersede this ADR rather than editing it.
The agentic-arm source is recoverable at tag `exp/pre-decomposition-simmer` (→ `58498de`).
