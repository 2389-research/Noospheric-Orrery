# Research Paper Spec — Experiments/Results Section

**Failure mode this guards against:** this is where most of the graph-worthy `model`/`task`/
`platform`/`apparatus` content is concentrated (baseline comparisons, ablations, named tasks with
outcomes) — the risk here is under-extraction from a weak model getting overwhelmed by density,
not over-extraction.

**Extra scrutiny for this section:**

- Lean toward recall over precision in this section specifically (the opposite bias from
  Introduction/Related Work) — a comparison table or ablation list naming 5+ baselines in one
  sentence should yield 5+ `model` entities, not just the first one or two.
- Every named task with a stated outcome (`shared.md` What to Extract #3) should be extracted even
  when tasks are listed tersely as a comma-separated list ("laundry folding, box assembly, table
  bussing") — don't drop later items in a list because the sentence structure is repetitive.
- Named `platform`/`apparatus` entities are most likely to be named precisely here (specific rig
  names, specific appliances) — apply `shared.md`'s platform/apparatus decision tree per entity.
