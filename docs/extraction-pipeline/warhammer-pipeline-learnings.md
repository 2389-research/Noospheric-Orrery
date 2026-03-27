# Warhammer Pipeline: In-Domain Learnings for Adaptive KG Extraction

**Date:** 2026-03-24
**Context:** This document captures empirical findings from building a domain-specific knowledge extraction pipeline over ~5,000 miniature painting YouTube tutorials. These learnings validate and inform the [Adaptive Knowledge Graph Extraction Design](../../infodesk-link/docs/superpowers/specs/2026-03-24-adaptive-knowledge-graph-extraction-design.md). The warhammer pipeline is the proof-of-concept; the adaptive system is the generalization.

## Pipeline Summary

```
YouTube transcripts (5,307 videos, 16 channels)
    → chunked LLM extraction (qwen3.5:27b, 5-min chunks)
    → 18-type entity taxonomy (41,988 raw mentions)
    → three-tier normalization cascade (→ 12,159 unique entities)
    → hybrid search (FAISS per-type + BM25 + graph + chunks, RRF fusion)
```

**Code location:** `DS-scratch/warhammer_mini_sizes/`
**Key files:** `batch_extract.py` (extraction), `normalize_plurals.py` → `embed_and_cluster.py` → `batch_cluster_review.py` → `apply_normalization.py` (normalization), `search/` (retrieval)

---

## 1. Extraction Prompt Quality > Model Quality

The single biggest lever is the extraction prompt, not the model.

**Evidence:** We tested 4 prompt versions (V1→V4) on the same `qwen3.5:27b` model. V1 produced noisy, inconsistent output. V4 (after 6 simmer iterations, 5.3→8.25/10) produced Sonnet-competitive quality. Switching from 9b to 27b helped, but the prompt evolution was the larger quality jump.

**What made the extraction prompt good:**
- A constrained taxonomy table (18 types with examples) — the model follows a table better than prose descriptions
- PRIORITY callouts for non-obvious categories ("painting theory concepts like color temperature, value contrast, reflection placement")
- Explicit IGNORE rules (clothing, food, furniture, YouTube metadata, generic single words)
- YES/NO extraction examples showing the boundary between concept-worth-extracting and generic observation
- The prompt tells the model exactly what JSON structure to return

**Implication for adaptive system:** Spec simmering is the right investment. A well-simmered spec on a cheap model outperforms a generic prompt on an expensive model. The spec's `entity_types` table, `extraction_notes`, `ignore_patterns`, and `examples` fields are where domain knowledge accumulates.

## 2. Taxonomy Emergence

The 18-type taxonomy was NOT designed upfront. It emerged through iteration:

- **V1:** Started with ~10 obvious types (technique, paint, tool, model, faction)
- **V2:** Added `concept` after noticing the model was missing painting theory
- **V3:** Added `body_area`, `assembly`, `basing` after seeing them lumped into `technique`
- **V4:** Added `aesthetic`, `skill_level`, `award` after corpus analysis showed they were distinct categories

**Key insight:** You can't predict the right taxonomy for a domain without looking at real data from that domain. The simmering process naturally discovers types by examining sample documents and noticing what's being missed or mis-categorized.

**Type distribution is very uneven:**
```
body_area:   5,000    concept:    4,622    model:     4,295
color:       4,167    technique:  3,721    medium:    2,629
paint:       2,483    tool:       2,390    person:    2,145
topic:       1,559    game_system:1,326    faction:   1,306
paint_brand: 1,304    aesthetic:  1,153    assembly:  1,152
basing:        710    award:        398    skill_level: 253
```

The long-tail types (`award`, `skill_level`) are low-frequency but high-value for queries. Don't prune types just because they're rare.

## 3. The Normalization Cascade Works

Three tiers, from cheap to expensive:

| Tier | Method | What it catches | Cost |
|------|--------|----------------|------|
| 1. Rules | Plural collapse (`edges→edge`), case normalization | Mechanical variants | ~Free |
| 2. Embeddings | `all-MiniLM-L6-v2` + agglomerative clustering (threshold=0.15) | Similar strings, word order flips, -ish suffixes | Cheap (batch embed) |
| 3. LLM review | `qwen3.5:27b` reviews each multi-member cluster | Transcript garbling, context-dependent merges, brand vs product | Moderate (but only on ambiguous clusters) |

**Results:** 14,033 unique raw names → 12,159 unique normalized names (13.4% reduction). 919 plural merges, 955 cluster merge groups, 1,151 renames.

**Critical lesson: what NOT to merge.** The LLM review prompt was simmered specifically to avoid false merges:
- `"dark beige" ≠ "light beige"` — different color shades
- `"3d printer" (tool) ≠ "3d printing" (assembly technique)` — tool vs activity
- `"artist opus" (brand) ≠ "artist opus one" (specific brush)` — brand vs product
- `"almost black" ≠ "almost white"` — embedding similarity doesn't mean semantic equivalence

**Embedding model matters:** SigLIP2 was useless for short text similarity (all hobby terms at cosine ~0.04). `all-MiniLM-L6-v2` from sentence-transformers worked well. Don't assume any embedding model handles short domain terms — test it.

**Implication for adaptive system:** The three-tier cascade is the right architecture. The cluster review LLM prompt should be simmered per-domain — what constitutes a valid merge is domain-specific.

## 4. Transcript Garbling is a Domain-Specific Problem

YouTube auto-captions garble domain terminology predictably:
```
"squid more miniatures" → "squidmar miniatures"
"warhammer on the world's warband" → "warhammer the old world"
"artistis opus" → "artist opus"
"fist on red" → "mephiston red"
"agrax earth shade" / "agrar's shade" → "agrax earthshade"
```

**Why this matters:** Edit distance doesn't catch these — they're completely different words. Only embedding similarity + LLM review handles them. The LLM doesn't need to know the correct product name; it needs to reason about whether two garbled strings could be the same entity given context.

**Implication for adaptive system:** Each domain will have its own garbling patterns. A medical domain will garble drug names differently than a hobby domain garbles paint names. The normalization review prompt needs domain context (the simmered spec should include known garbling patterns as they're discovered).

## 5. Relationship Extraction is Harder Than Entity Extraction

We chose NOT to extract typed relationships during entity extraction. Instead, we built co-occurrence edges from the graph:

- 12,159 entity nodes, 1,291,612 co-occurrence edges
- Edge weight = number of videos where both entities co-occur
- This was sufficient for graph-based retrieval (expanding from seed entities to related entities)

**Why we skipped typed relationships:**
- Entity extraction with qwen3.5:27b at 8.25/10 quality already pushes the model
- Adding relationship extraction to the same prompt would degrade entity quality
- Co-occurrence is "free" — computed from extraction output, no extra LLM calls
- For our retrieval use case, co-occurrence was good enough

**Where typed relationships would help:**
- Multi-hop queries ("what techniques does Trovarion use for NMM that Squidmar doesn't?")
- Recipe reconstruction ("what's the step-by-step for this NMM gold recipe?")
- Prerequisite chains ("what should I learn before attempting NMM?")

**Implication for adaptive system:** The spec should define `relationship_types` but extraction should be a separate pass (as iText2KG does). First pass: entities only. Second pass: relationships between extracted entities. This keeps each pass focused and the prompts manageable.

## 6. Chunking Strategy

**5-minute chunks with 30-second overlap** works well for YouTube tutorials.

**Why 5 minutes:**
- Long enough to capture context (a technique explanation typically spans 2-4 minutes)
- Short enough that the 27b model doesn't lose focus
- A 20-minute video = 4 chunks = 4 LLM calls ≈ 3-4 minutes total extraction time

**Why 30-second overlap:**
- Prevents entities from being split across chunk boundaries
- A painter might name a technique at 4:55 and the paint at 5:05 — overlap catches both

**Entity deduplication across chunks:** Merge on `name.lower().strip()`, keep first occurrence's type. Simple and effective — within a single video, the same entity mentioned in multiple chunks should converge to one entry.

**Implication for adaptive system:** Chunking strategy is domain-dependent and should be part of the simmered spec. Tutorials need time-based windowing. Research papers might need section-based chunking. Emails might not need chunking at all.

## 7. Search System Learnings

### Per-type FAISS indexes (Pattern 2) work well for structured entities

We built 19 separate FAISS indexes, one per entity type. This gives true pre-filtering:
- Query "NMM techniques" → search only the `technique` index
- Query "red paints" → search only the `paint` index
- Query "painting concepts" → search only the `concept` index

At 12K entities this is fine. At 100K+ entities per type, might need to switch to a vector DB with native filtering.

### BM25 + TF-IDF weighting is essential for keyword recall

FAISS misses exact keyword matches. BM25 (via SQLite FTS5) catches them. But raw BM25 returns globally common entities ("airbrush" appears in 304/659 videos). TF-IDF weighting fixes this:

```
score = (hit_count / n_matched_videos) * log(total_videos / global_count)
```

### Graph expansion fills retrieval gaps

FAISS can't match "NMM" to "non-metallic metal" (different embeddings). BM25 can't either (different strings). But if FAISS finds "reflection placement" and BM25 finds "value contrast," graph expansion from those seeds pulls in "non-metallic metal" because it co-occurs with both in 83+ videos.

**Specificity penalty for graph sources:**
```python
specificity = 1.0 / (1 + max(0, video_count - 100) / 100)
```
Without this, ultra-common hub entities like "airbrush" (304 videos, most graph neighbors) dominate graph expansion results.

### Query expansion is MANDATORY for production RAG

**This is the single most important finding for the adaptive system.**

Single query "painting NMM steel" → 0 relevant chunks returned. Expanded to 6 sub-queries → 4 chunks from the definitive Trovarion video on metal techniques.

**Why single queries fail:**
- Embedding models don't know domain abbreviations (NMM ≠ non-metallic metal in embedding space)
- Users think in high-level intent; indexes contain low-level entities
- A single query can't cover synonyms, related concepts, and the actual terminology simultaneously

**Expansion pattern that works:**
```
User: "painting NMM steel"
   → "painting NMM steel"                      (original)
   → "non-metallic metal silver"               (abbreviation expansion)
   → "NMM silver armor"                        (related sub-topic)
   → "painting steel effect without metallic"   (intent rephrased)
   → "reflection placement value contrast"      (domain concepts)
   → "cold grey blue highlight metal"           (color palette terms)
```

Fan out 4-6 sub-queries in parallel, dedupe results by (video_id, start_time) for chunks and (name, type) for entities, re-rank by aggregated score.

**Cost:** One fast LLM call for expansion + parallel search calls against existing indexes. Negligible compared to retrieval quality improvement.

## 8. What We'd Do Differently

1. **Extract relationships in a second pass from the start.** Co-occurrence is useful but typed relationships would enable much richer queries. The adaptive system's spec should include relationship types and extraction should be a distinct pipeline stage.

2. **Build the normalization into the extraction prompt.** Some garbling corrections (known autocaption errors) could be handled during extraction rather than in a separate normalization pass. The spec's `extraction_notes` field is the right place for this.

3. **Track extraction provenance more carefully.** Currently each entity knows which video it came from, but not which chunk or timestamp. For citation in RAG responses, you need chunk-level provenance.

4. **Start with more channels.** We began with 2 channels (Squidmar, Trovarion) and expanded to 16. The normalization quality improved significantly with more diverse data — the same technique described by different painters in different words gives the clustering more signal.

## 9. Corpus Scale and Performance

| Metric | Value |
|--------|-------|
| Videos mined | 5,307 enumerated, 4,720 transcripts fetched |
| Videos extracted | 1,935 (659 original + ~1,276 in progress) |
| Extraction speed | ~3-4 min/video on Spark GB10 (qwen3.5:27b Q4_K_M) |
| Normalization speed | Embed: ~5 min for 14K entities, Cluster review: ~3 hours for 1,253 clusters |
| Search index build | ~5 min (embedding is bottleneck) |
| Search latency | <2s per query (single path), <5s with all 4 paths |

**Scaling concern:** The co-occurrence graph grows quadratically. At 659 videos it's 1.3M edges (80MB GML). At 5,000 videos it could be 10M+ edges. May need edge pruning (drop edges with weight < threshold) or switch from NetworkX to a proper graph DB.

## 10. Testing the Adaptive System on This Corpus

This corpus is ideal for validating the adaptive system design:

**What to test:**
1. **Domain classification** — Feed the 5,307 video transcripts through the classifier. Does it correctly identify `hobby/miniature-painting`? Does it suggest useful subdomains (airbrush, NMM, speed painting, basing)?
2. **Spec simmering** — Let the system simmer its own extraction spec from 100 sample videos. Compare to our hand-crafted 18-type taxonomy. Does it discover similar types? Different ones? Better ones?
3. **Extraction quality** — Run the simmered spec against the same test videos we used for prompt development. Compare entity counts, coverage, precision against our V4 prompt baseline.
4. **Subdomain specialization** — There are clearly subdomains in this data (NMM techniques, airbrush work, basing/terrain, speed painting, competition painting). Does the system discover and specialize for them?
5. **Cross-extraction improvement** — Does extracting through both parent + subdomain specs produce meaningfully richer output than parent-only?

**Ground truth we have:**
- 659 fully extracted + normalized videos with known-good entity sets
- 3 test videos with Sonnet-grade ground truth extractions (in `local_extraction_tests/`)
- 12 hand-labeled normalization clusters (in `cluster_review_tests/`)
- Simmer trajectories documenting score progression for both extraction and cluster review prompts

**What we DON'T have:**
- Labeled relationship ground truth
- Cross-domain test data (everything is miniature painting)
- Quality metrics for the rough NER pass (Operation B)
