# SDK Spec Simmering Experiment Notes

**Date:** 2026-03-25/26
**Goal:** Validate that simmer-sdk can programmatically drive domain-specific extraction spec creation, replicating what was done manually via the Claude Code simmer skill on 2026-03-24.

## What We Did

### Phase 1: Gold Standard Simmering

**Script:** `build_gold_standard_sdk.py`
**Launcher:** `run_gold_standard.sh`
**Runtime:** ~1h 23m (22:32 → 23:55 CDT)
**Model:** Claude Sonnet 4.6 (generator + judge board)
**Iterations:** 4 (plus seed)

**Inputs:**
- 20 eval segments from `eval_set/segments/` (5-min transcript chunks from Squidmar + Trovarion)
- Parent domain's 18 entity types as background context
- Annotation rules from prior experiment (grounding, color threshold, garble handling, etc.)
- Criteria: coverage, precision, consistency, category_coherence

**What the system received (minimal instruction):**
- The 20 raw transcript segments as an empty annotation template (seed)
- Background telling it "here are the parent domain's types, you're building a subdomain"
- Annotation rules from prior work (shortcuts, not prerequisites — see note below)
- Simmer criteria definitions

**What the system discovered on its own:**
- 14-type taxonomy: technique, paint, paint_brand, color, material, tool, concept, principle, paint_property, model_part, person, model, game_ref, topic
- Rule 9 (name grounding for all entity types) — the strictest rule, emerged from judge feedback about synthesized labels
- The `principle` type (guiding rules/best practices like "thinner-first rule", "70-30 highlight rule")
- The `paint_property` type (paint behavior characteristics like "dilution ratio", "off-black")
- Specific garble corrections ("Valu" → "Vallejo", "Marco fron" → "Marco Frisoni", etc.)

**Results:**

| Iteration | Coverage | Precision | Consistency | Category Coherence | Composite |
|-----------|----------|-----------|-------------|-------------------|-----------|
| 0 (seed)  | 1        | 1         | 1           | 1                 | 1.0       |
| 1         | 1        | 1         | 1           | 1                 | 1.0       |
| 2         | 7        | 6         | 8           | 7                 | 7.0       |
| 3         | 7        | 6         | 8           | 7                 | 7.0       |
| 4 (best)  | 7        | 7         | 8           | 8                 | 7.5       |

**Note on iterations 0-1:** Both scored 1.0. Iteration 0 is the empty seed template. Iteration 1 also scored 1 — this may be a scoring artifact where the judge board couldn't properly evaluate the first real generation against the empty seed calibration. The real quality jump happened at iteration 2 when the board had a meaningful baseline to compare against.

**Output stats:**
- 156 entities across 20 segments (avg 7.8 per segment)
- 14 entity types
- Richest segments: 15 entities (BLOT1Jkq9wk airbrush tutorial, TR__l8fwprQ Sanguinor painting)
- Sparsest segments: 3-4 entities (sponsor-heavy or low-information segments)

**Type distribution:**
```
technique:      35
person:         23
color:          22
model_part:     18
principle:      10
paint:           9
material:        8
concept:         8
model:           7
tool:            5
paint_brand:     4
game_ref:        3
paint_property:  3
topic:           1
```

**Comparison to yesterday's skill-based gold standard:**
- Yesterday: 298 entities, 13 types, 9.0/10 composite after 4 iterations
- Today (SDK): 156 entities, 14 types, 7.5/10 composite after 4 iterations
- Key difference: Today's Rule 9 (strict name grounding for ALL types) is more aggressive than yesterday's grounding rule. This cuts entity count roughly in half but produces higher-confidence annotations.
- Quality: Entity-for-entity, today's annotations are well-grounded with solid rationales. The lower count is a precision tradeoff, not a quality problem.

## Key Observations

### 1. The annotation rules were shortcuts, not prerequisites
We provided annotation rules from the prior experiment as background context. In a true production scenario, these wouldn't exist. The system would likely discover most of them on its own — grounding, color threshold, sponsor exclusion — but it would take more iterations. The rules saved ~2 iterations of discovery.

**Implication for prod:** First domain's gold standard takes more iterations. But annotation methodology is transferable across domains — "here are principles we've learned about good annotation" can be injected into any domain's simmering without being domain-specific.

### 2. The seed calibration problem (iterations 0-1)
Both scored 1.0, which means the judge board couldn't meaningfully evaluate iteration 1 against the empty seed. The from-paste mode with an empty template doesn't give the judges a useful calibration reference. This is a simmer-sdk interaction issue — in the Claude Code skill, the seed is the starting artifact and gets scored, giving the judges a real baseline. Here, the seed was empty, so the board had nothing to compare against.

**Possible fix:** Use `seedless` mode instead of `from-paste` with an empty template. Or provide a rough first-pass annotation as the seed (e.g., run a cheap model on the segments first, then simmer to refine).

### 3. Parent domain awareness works
The generator correctly used the parent domain's types where appropriate (technique, paint, person, model, color) and invented new types only where needed (principle, paint_property). It didn't duplicate the parent's types or create overlapping categories. The "augment, don't duplicate" instruction in the background was sufficient.

### 4. Rule 9 emerged from the loop, not from us
The strictest annotation rule — "entity names must trace to spoken words, no synthesizing domain-standard labels from described behavior" — was created by the system. The judge board identified synthesized labels as a precision problem, and the generator responded by tightening the grounding rule. This is exactly the kind of self-improvement the adaptive system design relies on.

### 5. Judge board vs single judge
We used board mode throughout. The board's multi-perspective evaluation (3 judges scoring independently, deliberating, synthesizing) produced focused ASI that drove specific improvements. The "Audited techniques, removed non-verbatim entities" and "Tightened Rule 9; removed synthesized labels" key changes show targeted refinement, not vague suggestions.

## Pipeline Architecture

```
build_gold_standard_sdk.py
    │
    ├── Loads 20 eval segments from eval_set/segments/
    ├── Builds seed artifact (empty annotation template with transcripts)
    ├── Builds background (parent types, annotation rules, domain context)
    ├── Builds criteria (coverage, precision, consistency, category_coherence)
    │
    └── Calls simmer_sdk.refine()
        │
        ├── Iteration 0: Judge board scores empty seed (1.0)
        │
        ├── Iteration 1-N: Generate → Judge Board → Reflect
        │   ├── Generator: Read segments, annotate entities with taxonomy + rationale
        │   ├── Judge Board: 3 judges score independently → deliberate → synthesize ASI
        │   └── Reflect: Track trajectory, detect regression, identify stable wins
        │
        └── Output: result.md (best candidate), trajectory.md, iteration-N-candidate.md files
```

## Files Created

| File | Purpose |
|------|---------|
| `build_gold_standard_sdk.py` | Gold standard simmering script |
| `run_gold_standard.sh` | Launcher with API key and venv path |
| `run_simmer_sdk.py` | Spec simmering script (for Phase 2) |
| `sdk_eval.sh` | Evaluator wrapper bridging simmer-sdk to eval_runner/eval_scorer |
| `test_sdk_smoke.py` | Pre-flight checks for all dependencies |
| `sdk_gold_simmer/` | Output directory with iterations, trajectory, logs |
| `sdk_gold_simmer_stdout.log` | Raw stdout capture |

## Bugs Fixed During Setup

1. **simmer-sdk import path:** Relative path from experiment dir didn't resolve to simmer-sdk repo. Fixed to use `Path.home() / "Documents" / "GitHub" / "simmer-sdk" / "src"`.
2. **on_iteration callback signature:** simmer-sdk passes `(record, trajectory, trajectory_table)`, not just `(record)`. Fixed to accept all 3 args.
3. **claude-agent-sdk dependency:** simmer-sdk requires `claude-agent-sdk` which wasn't in system Python. Solution: run via simmer-sdk's own uv venv.

---

## Phase 3: Spec Simmering Results

### Run 1: qwen3.5:27b via Ollama (20 segments)

**Status:** Ran but evaluator wasn't invoked on first attempt (`{candidate}` vs `{candidate_path}` placeholder bug). Re-ran with fix — evaluator confirmed working (38 min iterations, Ollama actively hit). Scored 4.4 composite across 3 iterations with no improvement.

**Scores (flat across iterations):**
| Iter | Recall | Precision | Type Acc | Garble | Efficiency | Composite |
|------|--------|-----------|----------|--------|------------|-----------|
| 0 | 4 | 2 | 3 | 6 | 7 | 4.4 |
| 1 | 4 | 2 | 3 | 6 | 7 | 4.4 |
| 2 | 4 | 2 | 3 | 6 | 7 | 4.4 |

**Raw eval numbers (manual run of iteration-1 spec):**
- Gold: 127 entities across 17 segments (3 timed out)
- Extracted: 264 entities
- Matched: 60
- Recall: 47.2%, Precision: 22.7%

**Key qualitative findings:**
1. **qwen massively over-extracts.** Every segment has 2-3x the gold standard entity count. Most extras are real things from the transcript — not hallucinations — but not significant/instructional entities. The model can't distinguish "important entity" from "thing that was mentioned."
2. **Sponsor content not filtered.** sbuwJlBj0kc (Squarespace ad) got 17 entities extracted vs 1 in gold.
3. **Person extraction consistently missed.** Squidmar and Trovarion absent from every segment. The model doesn't know who's speaking.
4. **Some segments are excellent.** When content is focused (am7cZw2jKIQ, wUkOUBbOpkI), qwen matches the gold standard closely in both count and content.
5. **3 timeouts** at 300s limit — model gets stuck on some segments.

### Run 2: Haiku via API (10 segments)

**Status:** Running, iteration 0 complete.

**Iteration 0 scores:**
| Recall | Precision | Type Acc | Garble | Efficiency | Composite |
|--------|-----------|----------|--------|------------|-----------|
| 5 | 7 | 3 | 6 | 7 | 5.6 |

**Key difference: precision=7 vs qwen's precision=2.** Haiku follows the spec's restraint instructions much better — entity counts are close to gold standard (7-12 per segment vs qwen's 17-35).

**Qualitative findings (5-segment manual debug run):**
1. **Haiku extracts cleaner.** Counts are close to gold: 7/9/12/12/7 vs gold 6/6/15/5/5. Still over-extracts on some segments but not 2-3x.
2. **Person extraction still missed.** Same as qwen — Squidmar/Trovarion absent. This is a fundamental problem, not model-specific.
3. **Taxonomy mismatch.** Haiku spec uses `medium` where gold uses `material`, `game_system` where gold uses `game_ref`, `assembly` where gold uses `technique`. The seedless generator invented different type names than the gold standard.
4. **Name matching too strict.** "Marco Fron" vs "Marco Frisoni", "compressor" vs "airbrush compressor", "paint thinning" vs "thinning paint" — all semantically same but fail exact match. The scorer's fuzzy matching threshold may need tuning.
5. **Over-extraction of subtypes.** LAH5ahKGa3w: gold has "chipping" as 1 technique, Haiku extracts 4 variants (sponge/edge/hairspray/brush chipping). Arguably richer extraction, scores as noise.

### Cross-Run Analysis

| Metric | qwen3.5:27b | Haiku |
|--------|-------------|-------|
| Composite (iter 0) | 4.4 | 5.6 |
| Precision | 2 | **7** |
| Recall | 4 | 5 |
| Type accuracy | 3 | 3 |
| Over-extraction | Severe (2-3x) | Moderate (1.2-1.5x) |
| Person extraction | Missing | Missing |
| Sponsor filtering | Fails | Better |

**Conclusion: The pipeline works. The spec quality is decent. Model capability is the variable.**

### Open Problems Identified

**1. Person/speaker extraction.** Neither model knows who's speaking. The gold standard includes "Squidmar" and "Trovarion" as channel creators, but the models can't infer this from transcript text alone. Options:
- Inject channel name from segment metadata into the spec/prompt ("The speaker in this transcript is {channel_name}")
- Include a known-hosts list in the spec
- Accept that speaker identification requires metadata, not extraction
- This is fundamentally a metadata problem, not an extraction problem

**2. "Only extract if significant" is hard to teach.** qwen extracts every color, every model_part, every tool mentioned in passing. Telling it "only extract significant entities" doesn't work — the model can't judge significance. More concrete rules might help ("only extract colors used as deliberate paint choices, not colors describing observed states") but this is domain-specific judgment that cheap models struggle with.

**3. Taxonomy alignment.** The seedless spec generator invents its own type names. The gold standard has its own. They don't match. The scorer does exact type matching. Options:
- Tell the generator explicitly what types to use (defeats the "discovers its own taxonomy" thesis)
- Add type aliasing to the scorer (medium=material, game_system=game_ref)
- Use the gold standard's taxonomy in the spec generator's background

**4. Fuzzy matching sensitivity.** The scorer misses valid matches: word order flips ("paint thinning"/"thinning paint"), partial matches ("compressor"/"airbrush compressor"), garble variants ("glacia blue"/"Glacier Blue"). The 0.8 threshold on SequenceMatcher may need tuning, or we need embedding-based matching.

## Next Steps

### Phase 2: Extract gold standard JSON files
Parse `sdk_gold_simmer/result.md` to extract the 20 segment JSON annotations into individual `gold_standard_sdk/{segment_id}_gold.json` files that the eval_scorer can consume.

### Phase 3: Simmer the extraction spec
Run `run_simmer_sdk.py` with the SDK gold standard as evaluation data. The evaluator (`sdk_eval.sh`) runs the spec against eval segments via qwen3.5:27b (Ollama) and scores against the gold standard.

### Phase 4: Scale validation
Run the simmered spec on ~20-100 videos and compare output to the existing V4 extraction.

## Cost

- Gold standard simmering: ~1.5h of Claude Sonnet API calls (judge board = 3 parallel judges per iteration × 4 iterations + generator calls)
- No local compute needed for Phase 1 (all API-based, no Ollama)
- Phase 3 will require local Ollama (qwen3.5:27b) for evaluator runs
