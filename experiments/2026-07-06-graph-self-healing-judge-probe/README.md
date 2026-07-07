# Graph self-healing — correction-judge probe (rerun)

2026-07-06 · Complete, n=1 (single pass, temp=0) · Nomzor

## Question / hypothesis

Is the correction judge trustworthy enough to gate graph mutations? Specifically, can it
reject proposals that would **destroy or corrupt a real entity** (the dangerous failure
mode for a mutating graph)? This reruns the 2026-07-02 14-case blind probe, but through
the **decomposed relay judge** (`relay.complete_structured`, `think:false`) that v1
`judge_correction()` will actually ship — not the original ad-hoc live Claude subagents.
The original probe left no reusable artifact; this run captures one.

## Setup

- **Base commit (orrery):** `6147af8`
- **Harness (DS-scratch):** `41f9513` → `noospheric_graph_self_healing/` (`run_probe.py`, `cases.py`, `results.json`)
- **Judge:** one bounded, action-aware, adversarial (`try to refute`) `relay.complete_structured`
  call per case → `{verdict ∈ accept|reject|defer, confidence, rationale}`. `temperature=0`.
- **Model / backend:** `claude-sonnet-4-6` via **bedrock** (the `CLASSIFICATION_MODEL` / judge tier).
- **Data:** throwaway copy of `~/orrery-data/orrery.db` (production never touched). Read-only —
  no mutation applied (this probe measures verdict quality only).
- **Evidence pack per case:** entity current type(s) + **FULL** deduped source chunks
  (`entity_sources → chunks`) + neighborhood (top-15 co-occurrence neighbors). The "gather
  FULL chunks" lesson from the original probe is baked in.
- **Eval set:** 14 real proposals from `business/venture_capital/vc_firms`, both polarities,
  across all 4 v1 actions (invalidate · merge · retype · rename). **5 are negative controls**
  — proposals that would wreck a real entity; ACCEPTing one is the dangerous error.

## How to run

```bash
cd DS-scratch/noospheric_graph_self_healing
python3 -m venv .venv && .venv/bin/pip install -e <orrery>/packages/orrery-relay
.venv/bin/python run_probe.py     # reads <orrery>/.env for bedrock creds; writes results.json
```

## Results

| Metric | Value |
|---|---|
| Raw verdict-vs-label agreement | **12 / 14** |
| **False-accepts on negative controls** | **0 / 5** ✅ |
| False-accepts (total) | 0 |
| False-rejects (conservative disagreements) | 2 |
| Defers | 0 |
| Mean confidence — accept verdicts | 0.913 |
| Mean confidence — reject verdicts | 0.939 |

**The 5 negative controls were all rejected at 0.85–0.99** (invalidate `matrices`/`true ventures`,
merge firm-into-founder `cummer capital`↔`russell cummer`, retype `harper reed` Person→Org,
rename `harper reed`→"Harper Read"). Zero false-accepts — the result that matters is reproduced.

**Both disagreements were conservative (declined to mutate) and the judge out-reasoning the labels:**
- `inv-ebay` (label accept → **reject** @0.88): judge argued eBay is *substantively* discussed as
  an investment framework ("why did ebay feel so dumb obvious in 1996"), not a mere passing metaphor,
  so it declined to invalidate. Defensible.
- `rty-series-a` (label accept → **reject** @0.92): judge caught that `series a` **already carries a
  `FundingRound` type** (it's a multi-type row: Event / FundingRound / FundingStage / Investment Round),
  so the retype is redundant — the correct fix is to *remove* the `Event` type. Caught a data-model
  subtlety the label missed.

## Conclusion + caveats

The decomposed relay judge reproduces the original probe's core finding — **0 false-accepts across
the negative controls** — and both misses are conservative, correct-leaning refusals, not dangerous
greenlights. This supports the v1 design decision to ship the judge as **advisory** with a human gate
while collecting the calibration dataset.

**Caveats / differences from the 2026-07-02 subagent probe:**
- **n=1, temp=0, single model (Sonnet/bedrock).** Not a distribution — one pass.
- **Weaker calibration spread than the original.** Every verdict landed ≥0.85 and there were **no
  defers**; the original probe produced a low-confidence band (~0.68) on genuinely ambiguous cases.
  The decomposed judge is more confident across the board — worth watching, since confidence is what
  a future auto-apply gate would key on.
- **The ambiguous case flipped.** `commer capital`↔`cummer capital` was **accepted** here (0.92) but
  the 2026-07-02 probe *rejected* it. It is the one genuinely-ambiguous case; different judge
  mechanisms land differently on it. Neither is a negative control.
- **Open (unchanged): measure the gemma4 local-judge drop** on the source-grounded subset — same packs,
  same prompt, `ollama` backend. Not run here.

Related: design `docs/superpowers/specs/2026-07-02-graph-self-healing-human-reviewed-corrections-design.md`;
memory `usage-driven-self-healing-graph`.
