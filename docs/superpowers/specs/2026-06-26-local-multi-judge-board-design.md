# Design — Local Multi-Judge Board for the Simmer Loop

**Date:** 2026-06-26
**Status:** Draft for review
**Scope:** The local (non-agentic) text simmer pipeline — `worker/src/jobs/simmer_core.py`,
`simmer_general.py`, `simmer_domain.py`. **Out of scope:** the image simmer
(`simmer_domain_image.py`, still on agentic `refine()`) and any cloud/agentic execution path.

---

## 1. Background & Problem

The simmer loop (`generate → evaluate → judge → reflect`, steered by a single ASI) was restored in
PR #29 as a set of **bounded, non-agentic relay calls** so local models (gemma4) don't stall in
agentic loops. Today the judge is exactly one `relay.complete` per iteration (`relay_judge` in
`simmer_core.py`): everything pre-loaded inline, no tools, parsed by simmer-sdk's
`parse_judge_output`.

stock simmer-sdk supports a richer **judge board** (`judge_board.py`): a panel of judges with
different lenses, an independent scoring phase, a deliberation (cross-review) round, and a median
consensus + single synthesized ASI. But the SDK executes panelists **agentically** (even in ollama
mode: `run_local_agent(..., tools=["Read","Grep","Glob"], max_turns=25)`) — the exact loop that
stalls gemma4.

**Goal:** bring multi-judge capability to the local pipeline using the **same proven pattern as the
single judge** — reuse the SDK's pure-function prompt builders, parser, and consensus math; throw
away the agentic execution; drive everything with bounded `relay.complete` calls. Also make the
single-judge path optionally spend extra calls (self-consistency) where it measurably helps.

### Non-goals
- No change to the loop control flow, reflect/recording machinery, or context discipline.
- No new external dependency (simmer-sdk is already vendored).
- No board for the image pipeline.
- No always-on extra calls — the default stays exactly today's behavior.

---

## 2. Key Decisions (settled during brainstorming)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **A-menu + B-composer for panel selection.** A curated static library of judge lenses is the *menu*; one LLM "composer" call picks 1–3 lenses *from that menu*. | Constrained composition (pick from a fixed list, not free-form) keeps the composer's output short and parseable on a local model — de-risks pure LLM composition. |
| D2 | **Judge count N is low: 1–3.** Build and test with 1–2; N=3 supported but not required for v1 validation. | User-stated. Keeps cost bounded on serial-Ollama. |
| D3 | **Count-agnostic "combine" primitive.** Aggregation (median scores) + ASI synthesis operate on *N JudgeOutputs* regardless of whether the N came from N lenses (board) or K samples of one judge (self-consistency). | The combine code is then *not wasted* at N=1 — it doubles as self-consistency variance reduction. |
| D4 | **Unify with an N=1 fast path (option C).** Single judge entry point parameterized by count. N=1/K=1 = exactly today's generic judge (no composer, no deliberation, no consensus — bypassed). Composition + deliberation + consensus engage only at N≥2 (or K>1). | Unified surface, **zero regression** at the default. The thing PR #29 restored stays byte-for-byte at the floor. |
| D5 | **Reuse SDK pure functions; swap execution for relay.** `build_board_panelist_prompt` (+ `get_primitives_for_judge`), `build_deliberation_prompt`, `build_synthesis_prompt`, `compute_consensus_scores`, `parse_judge_output`. Never call `judge_board.py`'s agentic dispatch. | Same pattern that made `relay_judge` work. Most of the work is *assembly*, not invention. |
| D5a | **The menu-constrained composer (B) is NEW orrery code, not a reused SDK function.** The SDK's `build_board_composition_prompt` emits *free-form* judge definitions (it does not constrain the model to a fixed menu), so it's inspiration at most. Likewise the lens library is net-new authoring — `primitives.py` holds cross-cutting *primitives* (`seed_calibration`, `cluster_failures`…) that `get_primitives_for_judge` feeds *into* the panelist prompt, **not** judge lenses/personas. | Avoids the planner wiring up the wrong SDK function. |
| D6 | **Drop-in `JudgeOutput` contract.** The board returns the same `JudgeOutput` shape `relay_judge` returns today. | The loop, reflect, recorder, calibration, best-so-far are untouched. |
| D7 | **Self-consistency (K) default OFF.** K>1 is an opt-in knob, validated empirically before any default change. Its score-variance benefit is real; its ASI-quality benefit is unproven. | Don't bake in unproven cost. |

---

## 3. Architecture

### 3.1 Where it plugs in

`simmer_loop` (simmer_core.py:119) currently calls `relay_judge(...)` and expects a `JudgeOutput`
back. We introduce a single new judge entry point with the same return contract. The loop changes by
**at most** swapping which judge function it calls (via a settings switch); its body does not change.

```
simmer_loop
  └─ judge(candidate, evidence, criteria, settings, iteration, evaluator_output,
           seed_candidate, seed_scores, problem_class)  -> JudgeOutput
        │
        ├─ N==1 and K==1  ──► relay_judge (TODAY's path, unchanged)        [fast path / floor]
        │
        └─ N>=2 or K>1    ──► relay_board_judge                            [new]
```

### 3.2 `relay_board_judge` — the new orchestration

A mirror of `relay_judge`: deterministic Python around **bounded `relay.complete` calls**, no tools,
no agentic loop. Phases:

```
relay_board_judge(...):
  # Phase 0 — COMPOSE (only when panel not fixed; only at N>=2)
  panel = fixed_panel_from_config
          OR compose_panel_via_relay(library, criteria, candidate)   # 1 relay call, picks ≤N lenses from the menu
          # falls back to a sensible default sub-panel if parsing fails

  # Phase 1 — SCORE (independent)
  outputs = []                                  # list[JudgeOutput]
  for each (lens in panel) × (k in 1..K):
      prompt = build_board_panelist_prompt(lens, ... + NON_AGENTIC preamble)
      prompt += inline evidence (+ evaluator_output)        # same pre-loading as relay_judge
      outputs.append( parse_judge_output(relay.complete(prompt)) )

  # Phase 2 — DELIBERATE (only at panel size >= 2; one round)
  if len(panel) >= 2:
      for each judge:
          prompt = build_deliberation_prompt(own_output, other_outputs)
          outputs[judge] = parse_judge_output(relay.complete(prompt))   # revised scores/ASI

  # Phase 3 — COMBINE (count-agnostic)
  scores  = compute_consensus_scores([o.scores for o in outputs])       # median, pure Python (SDK)
  asi     = synthesize_asi(outputs)                                     # see 3.4
  return JudgeOutput(scores=scores, composite=mean(scores), asi=asi, reasoning=merged_reasoning)
```

Call-count per judge invocation: `compose? (0–1) + N×K (score) + N (deliberate, if N≥2) + asi-synth (0–1)`.
Example N=2, K=1, with composer + synthesis = `1 + 2 + 2 + 1 = 6` calls. N=1, K=3 (self-consistency,
no composer/deliberation) = `3 + asi-synth`.

### 3.3 The lens library (A) and composer (B)

- **Library:** a small **orrery-owned, net-new** set of named lenses, each a one-line description,
  tuned to our criteria. (These are judge *personas*, distinct from SDK `primitives.py`, which holds
  cross-cutting evaluation primitives — those are passed *into* `build_board_panelist_prompt` via
  `get_primitives_for_judge`, separately from the lens.) Candidate lenses (to be finalized in the
  plan), e.g.:
  - `coverage_hawk` — fixated on recall / missed entities
  - `precision_hawk` — fixated on noise / wrongly-extracted entities
  - `generalizability_skeptic` — flags hardcoded entity names, rewards general rules (spec phase)
  - `taxonomy_purist` — type meaningfulness/consistency/granularity (golden phase)
- **Composer:** one `relay.complete` that receives the library + criteria + a candidate snippet and
  returns the chosen lens *names* (≤N). Output is a short list — easy to parse. On parse failure or
  empty result, fall back to a fixed default sub-panel (no crash, no stall).
- Composer runs **once per judge invocation** (i.e. per iteration), not once per simmer run, so the
  panel can adapt as the artifact evolves. (Open question O3 — could be cached per run.)

### 3.4 ASI synthesis (the crux)

Median handles *scores*. The **ASI** is the single thing that steers the generator, so collapsing
N ASIs into one matters. Two candidate mechanisms (decide in plan, prefer the simpler that works):
- **(synth-call)** one `relay.complete` that reads the N judge outputs and writes the single
  highest-leverage ASI (this is what the SDK's synthesis does).
- **(pick-one)** deterministically pick the ASI from the judge whose criterion has the most headroom
  (lowest consensus score), no extra call.

v1 leans **synth-call** for fidelity to the SDK contract; **pick-one** is the cheaper fallback if the
synth call proves flaky on local models.

### 3.5 Context discipline (unchanged, must hold)

- The **generator still receives the synthesized ASI only** — never per-panelist scores, reasoning,
  evaluator output, or composer output.
- The judge still receives candidate + evidence (+ evaluator_output), calibrated to the frozen seed.
- Seed calibration (seed candidate + iteration-0 scores) is passed to **every** panelist on iter ≥1.

---

## 4. Configuration / Controls

New settings (env-driven, like the rest of `config.py`), with defaults that reproduce today:

| Setting | Default | Meaning |
|---------|---------|---------|
| `JUDGE_COUNT` (N) | `1` | Number of lenses on the panel (1–3). |
| `JUDGE_SAMPLES` (K) | `1` | Self-consistency samples per lens. |
| `JUDGE_PANEL` | `auto` | `auto` = composer picks; or a comma-list of lens names to fix the panel (bypasses composer — used to isolate composer effects in testing). |
| `JUDGE_DELIBERATE` | `true` | Whether the deliberation round runs (only relevant at panel size ≥2). |

N=1, K=1 ⇒ `relay_judge` unchanged. Any other combination ⇒ `relay_board_judge`.

`judge_mode` recorded in `simmer_iterations` becomes `relay-judge` (floor) or `relay-board`
(otherwise), so the trajectory/frontend can distinguish runs.

---

## 5. Recording / Observability

- **Consensus** scores/composite/asi recorded exactly as today (drop-in `JudgeOutput`) — no schema
  change required for the basic case.
- **Per-panelist detail** (each lens's scores + ASI, and the deliberation delta) is valuable for
  debugging and for the qualitative ASI review in testing. Options: (a) store as JSON in a new
  nullable column / side table, or (b) log-only for v1. **v1 = log-only + consensus in the existing
  tables**; per-panelist persistence is a fast-follow if the qualitative review needs it. (Open O4.)

---

## 6. Testing Plan

Two layers. The cheap behavioral run comes first; the rigorous decision apparatus is an **escalation
bought only if the cheap run looks promising** — not an upfront cost.

### Layer 1 — Structural / invariant tests (mocked LLM, deterministic, CI)
Mirror `worker/tests/test_simmer_core.py`. With judges mocked (`AsyncMock` side-effects):
- board returns a `JudgeOutput` (loop integration stays drop-in)
- `compute_consensus_scores` == median (pure-function)
- **N=1/K=1 reproduces today's single-judge path** (the critical no-regression guard)
- deliberation fires only at panel size ≥2; consensus is identity at N=1
- composer selects **only** library lenses (off-menu names rejected); parse-failure → default panel
- **context discipline holds**: generator gets synthesized ASI only — never per-panelist
  scores/evidence/composer output
- calibration seed reaches every panelist; every iteration still recorded

### Layer 2a — Cheap behavioral run (real gemma4, the user's proposal — do this first)
Fork one real simmer loop at the **same generator seed** into config variants and let them diverge
over ~3–4 iterations. Watch *behavior*, not winners:
- does the path run end-to-end without stalling / empty ASIs
- does it converge vs thrash
- do ASIs look sharper; are scores steadier
- wall-clock + call-count per config
- **for the spec phase, watch the F1 trajectory** — F1 is measured deterministically against the
  golden (not self-reported), so it's a non-circular signal available *for free*, no new reference
  set required.

> **Caveat that bounds this run:** per-iteration *scores* are the judge grading itself. A higher
> self-reported score is **not** evidence of real improvement (it can be score inflation — the exact
> thing seed-calibration fights). Use Layer 2a to judge behavior; use F1 (spec phase) for any
> objective read.

First experiments: `N=1/K=1` vs `N=1/K=3` (self-consistency variance look — K=3, since median of 2
only averages); then single vs a **fixed** 2-judge panel (`JUDGE_PANEL=` set explicitly, composer
bypassed).

### Layer 2b — Rigorous decision (only if 2a is promising)
To turn "looks better" into "is better, worth the cost":
- **Trusted frozen reference:** a small hand-verified chunk set + ground-truth entity list, so
  spec-phase F1 is trustworthy (the auto-golden is itself noisy).
- **Repeated runs:** ~5× per config on identical inputs; compare *distributions* (mean + spread),
  since self-consistency is a variance-reduction play.
- **Pre-registered bar:** e.g. "must lift final-spec F1 by ≥X or cut score variance by ≥Y to justify
  N× the calls — else default stays N=1/K=1."
- **Isolate composer from panel:** test a fixed hand-picked panel first, then composer-chosen, so a
  bad result is attributable.
- **ASI quality:** no clean metric — qualitative pass over recorded per-iteration ASIs.

### Test ladder (staged)
1. Structural (mocked) — CI.
2. Cloud/Sonnet smoke — board emits valid `JudgeOutput` end-to-end with real calls.
3. Variance study (gemma4): N=1/K=1 vs N=1/K=3.
4. Panel study (gemma4): single vs fixed 2-judge, then composer-chosen.
5. Cost table throughout (calls + wall-clock).

### Harness
A config-matrix runner (extend the existing `scripts/pipeline_smoke.py` pattern) that takes fixed
inputs, sweeps N×K (and fixed-vs-auto panel), and emits F1 / score-variance / call-count / wall-clock
per cell.

---

## 7. Performance / Cost note (the real tradeoff)

Ollama serves one model at a time, so "parallel" panelists are effectively **serialized**. One judge
today = 1 call/iteration. A 2-judge board with composer + deliberation + synthesis ≈ 6 calls/iteration
*per phase*. This is the dominant cost — code effort is Medium; **wall-clock is the thing to design
around.** This is why N is capped low, K defaults off, and deliberation is a toggle.

---

## 8. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Re-introducing agentic stalls | Never call `judge_board.py` dispatch; reuse only its pure functions. NON_AGENTIC preamble + inline evidence on every panelist, exactly like `relay_judge`. |
| Composer emits garbage on local model | Constrain to menu; parse to lens names only; fall back to fixed default panel on failure. |
| Silent regression of the restored single judge | N=1/K=1 hard-routes to today's `relay_judge`; structural test asserts equivalence. |
| ASI synthesis flaky on local model | `pick-one` deterministic fallback; default off-ramp if synth-call underperforms. |
| Reading too much into a single stochastic run | Layer-2a caveat documented; objective decisions gated on Layer-2b (reference + repeats + bar). |
| Scope creep into image pipeline | Explicitly out of scope. |

---

## 9. Open Questions (resolve during planning)

- **O1:** ASI synthesis mechanism — `synth-call` vs `pick-one` for v1.
- **O2:** Final lens library contents and whether lenses are phase-specific (golden vs spec criteria differ).
- **O3:** Composer cadence — per-iteration (adaptive) vs once-per-run (cached, cheaper).
- **O4:** Per-panelist persistence — log-only vs new column/side-table in v1.
- **O5:** Whether `JUDGE_DELIBERATE` is worth shipping in v1 or deferred until 2a shows panels help at all.

---

## 10. Effort Summary

**Medium**, mostly assembly. The loop integration is a drop-in (`JudgeOutput` contract); the SDK
already provides prompt builders, parser, consensus math, and lens primitives as pure functions we
already vendor. New work concentrated in `relay_board_judge` orchestration, the lens library + a
constrained composer, the config surface, structural tests, and the matrix harness.
