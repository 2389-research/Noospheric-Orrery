# Multi-Judge Board — gemma4 Validation Findings

**Date:** 2026-06-26
**Branch:** `feat/local-multi-judge-board`
**Status:** Directional (n=2/arm) — promising, not yet a verdict to change defaults.

Validation of the optional multi-judge board (see the design + plan docs in this dir) against the
**real** domain-simmer flow on a local model.

## Method (the valid one)

Ran the actual `run_simmer_domain` pipeline, **varying only the judge config** (env knobs), so the
comparison reflects production behavior:
- Models: `gemma4:26b` (judge/composer/synthesis) + `gemma4:e4b` (extraction), via Ollama.
- Domain: `business/product_development/strategy`. **Input pinned** to a fixed 10-chunk sample (in a
  DB copy) so the judge is the only variable across runs.
- Seed + 2 rounds (`iterations=2`); both Phase 1 (golden) and Phase 2 (spec) judged.
- Arms: floor (`N=1/K=1`) ×2 vs board (`N=2/K=1`, `panel=auto`) ×2.
- Isolation: per-run DB copy + temp `SPECS_DIR`; queued batch-extraction stays inert.
- Driver: `scripts/domain_judge_experiment.py`. Evaluation: Claude reading the artifacts
  (golden + spec + per-round ASIs), **not** exact-match F1 (too brittle — valid entity, wrong type).

## Results

| variant | golden entities | grounded in source | golden composite | spec composite | wall-clock |
|---|---|---|---|---|---|
| floor_r1 | 17 | 100% | 8.0→8.7→8.3 | 6.0→6.0→7.0 | 193s |
| floor_r2 | 10 | 100% | 9.0→9.3→9.3 | 3.3→5.7→5.0 | 214s |
| board_r1 | 25 | 96% | 8.3→8.7→9.3 | 4.3→5.0→6.0 | 445s |
| board_r2 | 21 | 90% | 8.3→8.7→8.7 | 5.7→5.3→6.3 | 460s |

(Composites are per-variant self-reports — compare *shape*, not absolute level.)

## Findings

- **Board's clearest, theory-consistent edge is the GOLDEN/taxonomy phase.** The board judge
  repeatedly proposed **structural** taxonomy ASIs in BOTH runs — *"introduce a new type
  `technical_stack_or_tool` to stop the taxonomy becoming a catch-all"*, *"split `use_case`"*,
  *"sub-types for `strategy`"*. The floor judge gave almost exclusively flat *"add entity X"* coverage
  in BOTH runs. Result: board goldens are richer and **better-typed** — board correctly grouped
  `rust`/`python`/`astro` as tools and `sprints`/`retro`/`fresh eyes` as methodology, where floor
  **mis-typed** `astro`/`gatsby` as `market_segment` and `betaworks` as `business_model`.
- **Coverage vs tidiness trade.** Floor goldens are 100% grounded but thin (10–17) and mis-typed;
  board goldens are broader (21–25) and better-organized but let in a few weak/fragment spans
  (`"influencing them"`, `"setting the tone for the conversation"`, `"weekly daily kind of process"`).
- **Board also uniquely captured the metric layer** floor dropped (`$500k`, `around $2m`,
  `cost to serve` as `business_metric`).
- **Spec phase: gap marginal.** Floor produced equally good evidence-based spec ASIs (cited real
  precision/recall, even self-corrected a backfiring rule). Board's were slightly more surgical
  (*"strip leading/trailing verbs — extract 'sniper market' not 'work with the sniper market'"*).
- **Convergence:** board climbed more monotonically; floor oscillated. **Cost ≈ 2.3×** (board now
  runs in both phases).
- **Shared weakness (not board-specific):** fragment-y entities survive in the *golden* of every
  variant — the golden isn't span-cleaned the way the spec-phase EXCLUDE rules try to be.

## Caveats
- **n=2/arm** — directional, not significant; within-arm variance is real.
- **Domain-type *discovery* is judge-INDEPENDENT** (a pre-loop classification call), so type-set
  differences between runs are variance, not a board effect. The board's *structural ASIs during the
  golden loop* are the genuinely judge-driven improvement.

## Verdict
On real artifacts the board produces the **more useful knowledge-graph seed** (broader,
correctly-typed, structured) at ~2.3× compute and a few sloppy spans. Promising and worth a larger
study; **do not flip the default** — ship as **opt-in** for taxonomy-sensitive domains (the
inert-by-default `N=1/K=1` knob already supports this). A real verdict needs: (1) a trusted
hand-checked golden, (2) a generator that reliably applies ASIs, (3) repeated runs / a held-out split.
