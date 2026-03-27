# Adaptive Entity Extraction Pipeline Guide

**Date:** 2026-03-27
**Status:** Proven via experiment, ready for productionization
**Authors:** Michael Sugimura, Claude (Opus 4.6)

This document captures everything learned from the adaptive spec simmering experiment (2026-03-24 through 2026-03-27). It serves as the reference for building a production orchestration layer around the proven pipeline.

---

## What We Built and Proved

A fully automated pipeline that:
1. Takes raw documents from an arbitrary domain
2. Builds a gold standard annotation set (no human labeling)
3. Simmers an extraction spec optimized for a cheap execution model
4. Runs that spec to extract structured entities from documents

**Total cost:** ~$15-20 per domain (Anthropic API). Zero human prompt engineering.

**Key result:** 228 entities extracted across 20 painting tutorials, with a 15-type taxonomy discovered automatically by the system. The pipeline works end-to-end.

---

## The Proven Pipeline

### Phase 1: Gold Standard Simmering

**What it does:** Annotates a sample of documents (20 segments) with high-quality entity labels. Discovers the domain's entity taxonomy, annotation rules, and edge case decisions.

**Script:** `build_gold_standard_sdk.py`
**Models:** Sonnet 4.6 (generator + judge board)
**Runtime:** ~1.5 hours for 4 iterations
**Cost:** ~$5-10

**Inputs:**
- 20 document segments from the domain (eval set)
- Parent domain entity types (if this is a subdomain) — tells the system what already exists so it augments rather than duplicates
- Annotation rules from prior domains (optional — saves ~2 iterations if available, but the system discovers its own rules if not provided)

**Outputs:**
- `result.md` — annotated document with entity JSON per segment + taxonomy + rules
- Individual `{segment_id}_gold.json` files (extracted via `extract_gold_from_result.py`)
- Trajectory showing score progression

**What the system discovers on its own:**
- Entity type taxonomy (we got 14 types: technique, paint, paint_brand, color, material, tool, concept, principle, paint_property, model_part, person, model, game_ref, topic)
- Annotation rules (grounding, color threshold, garble handling, sponsor content filtering)
- Rule 9 (strict name grounding) emerged from judge feedback — the strictest rule was self-discovered
- The `principle` type (guiding rules like "thin your paints") — novel type not in parent taxonomy
- The `paint_property` type (paint behavior characteristics) — novel type

**Results:** 156 entities, 14 types, 7.5/10 composite after 4 iterations with judge board.

### Phase 2: Extraction Spec Simmering

**What it does:** Iteratively refines a prompt that a cheap execution model (Haiku) can use to extract entities from new documents, evaluated against the gold standard.

**Script:** `run_simmer_sdk.py` (or `run_simmer_sdk_haiku.py` for Haiku execution)
**Models:** Sonnet 4.6 (generator + judge board), Haiku 4.5 (execution/evaluator)
**Runtime:** ~1.5 hours for 5 iterations (with Haiku evaluator)
**Cost:** ~$5-10

**Inputs:**
- Gold standard from Phase 1
- Background context (parent domain types, domain sample, lessons learned)
- Evaluation criteria (recall, precision, type_accuracy, garble_handling, prompt_efficiency)

**Outputs:**
- Versioned extraction specs (iteration-N-candidate.md)
- Best spec (result.md / sdk_best_spec.md)
- Trajectory with per-criterion scores

**Best result:** Iteration 1 scored 6.1/10 composite (recall=6, precision=7, type_accuracy=5, garble_handling=6, prompt_efficiency=6).

### Phase 3: Batch Extraction

**What it does:** Runs the best extraction spec on full documents via the cheap execution model.

**Script:** `run_haiku_20_tutorials.py`
**Model:** Haiku 4.5
**Runtime:** ~15-30 min for 20 videos
**Cost:** ~$1-2

**Process:**
1. Chunk each document into 5-minute windows with 30s overlap
2. Extract entities from each chunk via Haiku + spec
3. Deduplicate within each document (merge on lowercase name)

**Output:** Per-document JSON with deduplicated entities (name, type, rationale).

**Result:** 228 entities across 20 tutorials, 15 types, zero errors.

---

## Model Stack Decision: Sonnet + Haiku

We tested two execution models:

| | qwen3.5:27b (local) | Haiku 4.5 (API) |
|---|---|---|
| Precision | 2/10 (massive over-extraction) | 7/10 (clean) |
| Recall | 4/10 | 5-6/10 |
| Cost | Free (local GPU) | ~$0.05-0.10 per video |
| Speed | 1-5 min per segment | 2-5 sec per segment |
| Instruction following | Poor on restraint rules | Good |

**Decision: Sonnet for simmering (generator/judges), Haiku for extraction.**

Haiku follows the spec's restraint instructions far better than qwen3.5:27b. The precision difference (7 vs 2) means Haiku produces usable output on the first attempt while qwen floods the graph with noise. The cost is minimal ($0.05-0.10 per video).

Sonnet stays as the generator and judge because those roles require reasoning about domain understanding, extraction quality, and spec refinement — tasks that need a more capable model.

**For users who want free/local execution:** The pipeline supports any execution model. qwen needs a much more aggressive spec with explicit restraint rules, fewer entity types, and stricter filtering. This is achievable with more simmering iterations focused on the model's weaknesses — the pipeline supports it, we just need to invest more iterations.

---

## Pipeline Architecture for Production

```
User adds documents to service
    │
    ├─ Classify into domain (Sonnet, expensive, once per doc)
    │   → "hobby/miniature-painting", "business/meetings", etc.
    │   → Can propose new domains
    │
    ├─ Lightweight entity extraction (Haiku, cheap, immediate)
    │   → Rough entities in graph, queryable immediately
    │
    ▼
Domain Registry tracks document counts
    │
    ├─ Domain hits threshold (N=100 default)
    │   │
    │   ▼ Trigger: Simmer Pipeline
    │   │
    │   ├─ Phase 1: Gold Standard Simmering (Sonnet, ~1.5h, ~$5-10)
    │   │   → Sample 20 segments from domain
    │   │   → Build annotated gold standard with taxonomy
    │   │   → Extract gold JSON files
    │   │
    │   ├─ Phase 2: Extraction Spec Simmering (Sonnet + Haiku, ~1.5h, ~$5-10)
    │   │   → Iteratively refine spec evaluated against gold standard
    │   │   → Best spec becomes the domain's extraction configuration
    │   │
    │   └─ Phase 3: Batch Extraction (Haiku, ~$0.05-0.10/doc)
    │       → Run spec on all documents in domain
    │       → Rich domain-specific entities added to graph
    │       → Normalization pass (embed → cluster → reconcile)
    │
    ├─ New document arrives in domain with existing spec
    │   → Extract immediately using current spec version (Haiku)
    │
    └─ Re-simmering trigger (time, count growth, manual)
        → Re-simmer with larger corpus
        → Re-extract all domain documents
```

---

## What Worked Well

1. **Simmer-SDK as the engine.** The programmatic `refine()` API cleanly drives the gold standard and spec creation. Judge board with 3 parallel judges produces focused ASI. Regression detection and stable wins tracking prevent quality loss.

2. **Gold standard simmering discovers taxonomy.** The system found 14 entity types, including `principle` and `paint_property` which weren't in the parent domain. Annotation rules (grounding, color threshold, garble handling) emerged from judge feedback.

3. **Parent domain awareness.** Telling the generator "here are the types that already exist, augment them" produced entities that complement rather than duplicate the parent extraction.

4. **The spec quality is high.** The generated extraction prompts include taxonomy tables, YES/NO boundary examples, garble correction lists, action-to-technique mappings, and IGNORE rules — all discovered automatically.

5. **Haiku as execution model.** Precision=7 out of the box. Clean entity extraction at $0.05-0.10 per video. Fast enough for real-time extraction on ingest.

---

## What Didn't Work / Lessons Learned

### 1. Person/Speaker Extraction Requires Metadata

**Problem:** Neither qwen nor Haiku can figure out who's speaking in a transcript. "Squidmar" and "Trovarion" were consistently missed — the model has no way to know the channel creator from text alone.

**Solution for production:** Inject document metadata into the extraction prompt. If we know the channel name, author, or speaker, include it: "The speaker in this transcript is {channel_name}. Always extract them as a person entity."

**This is a metadata problem, not an extraction problem.** The pipeline needs the orchestration layer to pass document metadata alongside content.

### 2. "Only Extract If Significant" Is Hard to Teach Cheap Models

**Problem:** qwen3.5:27b extracted every color, every model part, every tool mentioned in passing. Telling it "only extract significant entities" doesn't work — the model can't judge significance.

**What helps:**
- Concrete rules instead of abstract instructions ("only extract colors used as deliberate paint choices, not colors describing observed states")
- Explicit IGNORE lists with examples
- The `principle` vs `concept` distinction gives the model a concrete decision framework

**For production:** The simmered spec handles this — it generates domain-specific restraint rules. But expect cheap models to need more iterations of simmering focused on precision.

### 3. Taxonomy Alignment Between Gold Standard and Spec

**Problem:** The seedless spec generator invented different type names than the gold standard (e.g., `medium` vs `material`, `game_system` vs `game_ref`). The scorer does exact type matching, so these count as wrong.

**Solution for production:** Either:
- Tell the spec generator explicitly which types to use (provide the gold standard's taxonomy in the background)
- Add type aliasing to the scorer
- Both — the gold standard taxonomy should be a constraint on the spec generator

### 4. Fuzzy Matching in the Scorer Needs Tuning

**Problem:** Valid matches missed: "paint thinning" vs "thinning paint" (word order), "compressor" vs "airbrush compressor" (subset), "Marco Fron" vs "Marco Frisoni" (garble). The 0.8 SequenceMatcher threshold is too strict for domain terminology.

**Options:**
- Lower threshold (0.7 or 0.65)
- Add containment matching (if one name contains the other, match)
- Embedding-based matching (like the normalization pipeline)
- All of these would improve reported recall/precision by 10-15%

### 5. Evaluator Template Variable

**Bug:** The simmer-sdk uses `{candidate_path}` as the template variable in evaluator commands. We initially used `{candidate}` which was never replaced, so the evaluator silently failed. The first full run's scores (6.0-7.0) were judges evaluating the spec text structurally, not actual extraction output.

**Fix applied:** Use `{candidate_path}` in the evaluator command string.

**For production:** Document the evaluator interface clearly. The simmer-sdk evaluator command supports: `{candidate_path}`, `{output_dir}`, `{iteration}`.

### 6. Chunking Needs Transcript Format Awareness

**Problem:** The 5-minute chunking assumes `[MM:SS]` timestamp format. Some transcripts use different formats or have no timestamps, resulting in single-chunk extraction (less entity diversity).

**For production:** The chunking strategy should be part of the simmered spec (it already is in the design). Different content types need different chunking: time-based for video transcripts, section-based for papers, paragraph-based for emails.

### 7. Annotation Rules Are Transferable Shortcuts

**Problem framing:** We injected annotation rules from prior experiments into the gold standard simmering. In a true production scenario, these wouldn't exist for the first domain.

**Finding:** The system discovers most rules on its own (grounding, color threshold, garble handling) — they just take ~2 extra iterations. Rules are not prerequisites, they're shortcuts.

**For production:** Accumulate annotation methodology across domains. "Here are principles we've learned about good annotation" can be injected into any new domain's simmering without being domain-specific. This is another form of "the system gets smarter over time."

---

## File Inventory

### Scripts (the pipeline)

| File | Purpose | Run time |
|------|---------|----------|
| `build_gold_standard_sdk.py` | Phase 1: Simmer gold standard annotations | ~1.5h |
| `extract_gold_from_result.py` | Phase 1→2: Parse result.md into gold JSON files | Instant |
| `run_simmer_sdk.py` | Phase 2: Simmer extraction spec (qwen evaluator) | ~3-6h |
| `run_simmer_sdk_haiku.py` | Phase 2: Simmer extraction spec (Haiku evaluator) | ~1.5h |
| `eval_runner.py` | Evaluator: Run spec on segments via Ollama qwen3.5:27b | ~30min |
| `eval_runner_haiku.py` | Evaluator: Run spec on segments via Haiku API | ~2min |
| `eval_scorer.py` | Scorer: Fuzzy match extraction vs gold standard | Instant |
| `run_haiku_20_tutorials.py` | Phase 3: Batch extraction on full tutorials | ~15-30min |

### Launcher scripts

| File | What it runs |
|------|-------------|
| `run_gold_standard.sh` | Phase 1 with API key and venv |
| `run_spec_simmer.sh` | Phase 2 (qwen) with pre-flight checks |
| `run_spec_simmer_haiku.sh` | Phase 2 (Haiku) |
| `run_haiku_tutorials.sh` | Phase 3 on 20 tutorials |
| `run_full_pipeline.sh` | Phases 1→2→3 end-to-end (supports `--skip-gold`) |
| `sdk_eval.sh` | Evaluator wrapper for qwen pipeline |
| `sdk_eval_haiku.sh` | Evaluator wrapper for Haiku pipeline |

### Data

| Directory | Contents |
|-----------|----------|
| `eval_set/segments/` | 20 eval transcript segments (5-min chunks) |
| `sdk_gold_simmer/` | Gold standard simmer output (iterations, trajectory, result.md) |
| `sdk_gold_standard/` | 20 gold JSON files (156 entities, 14 types) |
| `sdk_spec_simmer/` | qwen spec simmer output |
| `sdk_spec_simmer_haiku/` | Haiku spec simmer output (best: iteration-1, 6.1/10) |
| `haiku_20_tutorial_extraction/` | 20 full tutorial extractions (228 entities, 15 types) |
| `sdk_eval_debug/` | Manual qwen eval output for debugging |

### Documentation

| File | Contents |
|------|----------|
| `DATA_MANIFEST.md` | Full paths, JSON schemas, type taxonomy for graph agent |
| `graph_data_spec.md` | Graph structure recommendations, co-occurrence data |
| `sdk_experiment_notes.md` | Detailed experiment log with analysis |
| `PIPELINE_GUIDE.md` | This document |

---

## Dependencies

- **simmer-sdk** (`~/Documents/GitHub/simmer-sdk/`) — programmatic simmer refinement loop
  - Requires: `anthropic>=0.40.0`, `claude-agent-sdk>=0.1.50`
  - Use its venv: `~/Documents/GitHub/simmer-sdk/.venv/bin/python`
- **Anthropic API key** — for Sonnet (simmering) and Haiku (extraction)
- **Ollama** (optional) — only if using qwen3.5:27b for local extraction

## Design Spec

The broader adaptive knowledge graph extraction system design:
`/Users/michaelsugimura/Documents/GitHub/infodesk/docs/superpowers/specs/2026-03-24-adaptive-knowledge-graph-extraction-design.md`

This experiment validates sections 3 (spec simmering) and 4 (domain-specific extraction) of that design.
