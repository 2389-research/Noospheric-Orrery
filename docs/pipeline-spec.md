# Noospheric Orrery — Pipeline Specification

**Date:** 2026-03-27
**Status:** Draft
**Purpose:** End-to-end pipeline from document upload to knowledge graph visualization

## Overview

A user uploads documents (files, directories, links). The pipeline extracts a knowledge graph — entities, relationships, domains — and visualizes it. No manual spec authoring. The system discovers domains, builds extraction specs, normalizes entities, and refines itself as the corpus grows.

## User-Facing Surfaces

1. **Ingest page** — upload files, add directories. Shows pipeline progress as documents are processed.
2. **Viz page** — cosmic visualization (domains as nebulae, entities as stars). Interactive exploration of what the graph knows.
3. **Search page** — semantic search over entities and documents. Lower priority — the underlying capability works, just needs a UI.

## Pipeline Flow

```
User uploads documents
    │
    ├─ Step 1: Domain Classification (Sonnet)
    │   → Proposes domains for each document
    │   → Normalization cascade on domains (cluster, merge, taxonomy)
    │
    ├─ Step 2: First-Pass Extraction (Haiku, generic spec)
    │   → Generic spec covers: people, places, things, ideas, concepts
    │   → Extracts immediately — graph is queryable from first upload
    │   → Normalization cascade on entities
    │
    ├─ Step 3: Golden Set Simmering (Sonnet, per domain or full corpus)
    │   → Selects representative docs from domain
    │   → Builds golden set of concepts, entities, relationships
    │   → Accounts for existing entities (avoids re-pulling known stuff)
    │   → Simmer refines the golden set
    │
    ├─ Step 4: Extraction Spec Simmering (Sonnet judges, Haiku execution)
    │   → Templates spec files from golden set
    │   → Simmer refines the prompt for Haiku extraction
    │   → Evaluator tests spec against held-out docs
    │
    ├─ Step 5: Domain-Specific Re-Extraction (Haiku, simmered spec)
    │   → Runs simmered spec on all docs in domain
    │   → Normalization cascade on new entities
    │   → Merge into graph
    │
    └─ Step 6: Visualization Update
        → Graph updated, viz page reflects new entities/domains
```

## Step 1: Domain Classification

**Model:** Sonnet (needs to be performant — domains can be wide-ranging and subtle)

**Input:** Document content + existing domain taxonomy

**Output per document:**
- Primary domain path (e.g., `techniques/wet-blending`)
- Secondary domains if applicable (e.g., `theory/color-theory`)
- Suggested new domains not yet in taxonomy

**Domain Taxonomy:**

Domains are organized hierarchically. The taxonomy is a living document that grows as new content arrives.

```
region/
  parent-domain/
    subdomain/
```

Example (miniature painting):
```
techniques/
  wet-blending/
  drybrushing/
  airbrush/
    zenithal/
fundamentals/
  brush-control/
  color-mixing/
theory/
  color-theory/
  light-placement/
```

**Domain Normalization Cascade:**

After classification, normalize domain labels:
1. **Embed** all domain labels (including new proposals)
2. **Cluster** similar labels (cosine similarity)
3. **Pick canonical name** — highest frequency label in cluster
4. **LLM review** — for ambiguous clusters, confirm merge or keep separate
5. **Update merge map** — "zenithal priming" → "zenithal", "glow effects" → "osl"
6. **Update taxonomy** — add new domains, promote subdomains when warranted

Store as documented taxonomy with merge rules so the same normalization decisions don't need to be re-made.

## Step 2: First-Pass Extraction

**Model:** Haiku (cheap, runs on every document immediately)

**Spec:** Generic — not domain-specific. Covers broad entity categories:
- **People** — names, roles, organizations
- **Places** — locations, regions, settings
- **Things** — objects, tools, products, materials
- **Ideas** — concepts, theories, principles, methods
- **Actions** — techniques, processes, procedures

This is intentionally broad. The point is immediate queryability — get *something* in the graph for every document right away. Domain-specific extraction (Step 5) adds depth later.

**Output:** Entities with types, source document, chunk references

**Entity Normalization Cascade (after first pass):**
1. **String normalization** — lowercase, strip whitespace, punctuation
2. **Plural collapse** — only when both forms exist in corpus
3. **Embedding similarity** — cluster similar entity names (all-MiniLM-L6-v2)
4. **LLM review** — for ambiguous clusters, confirm merge or keep separate
5. **Pick canonical name** — highest frequency member of cluster
6. **Store merge map** — so future extractions auto-normalize

Same cascade as domain normalization, applied to entities.

## Step 3: Golden Set Simmering

**Purpose:** Build a high-quality reference set of entities for a domain. This is what "good extraction" looks like — the gold standard that extraction specs are evaluated against.

**Triggered by:** First corpus upload (full corpus), or when a domain grows large enough to warrant specialization.

**Process:**
1. **Select representative documents** from the domain (or full corpus for initial run). Sample for diversity — different subtopics, different content styles, different lengths.
2. **Review existing entities** on those documents from first-pass extraction. Note what's already been found so the golden set doesn't just re-discover the obvious stuff.
3. **Build golden set** — Sonnet reads the selected documents deeply and produces a comprehensive entity set with types, relationships, and edge cases. This is the expensive, thorough pass.
4. **Simmer the golden set** — iteratively refine against criteria:
   - Coverage: captures everything a domain expert would want
   - Precision: no noise, no hallucinated entities
   - Taxonomy quality: entity types are meaningful and consistent
   - Relationship quality: connections are real, not just co-occurrence

**Output:** A golden set of entities + relationships + a validated entity type taxonomy for this domain.

**This is Phase 1 from the extraction pipeline experiments.** The experiment validated it works — 156 entities, 14 types, 7.5/10 composite after 4 iterations on miniature painting tutorials.

## Step 4: Extraction Spec Simmering

**Purpose:** Build a prompt that makes Haiku extract entities matching the golden set's quality. The golden set says what to extract; the spec tells Haiku how.

**Process:**
1. **Template the spec files** — largely boilerplate with domain-specific inserts (entity types from golden set, examples from golden set, known garbling corrections, normalization hints)
2. **Simmer the extraction prompt** — iteratively refine the Haiku prompt:
   - Evaluator runs the prompt against held-out docs
   - Scorer compares extracted entities against golden set
   - Judges (investigation-first, board for complex domains) analyze failures and propose improvements
   - Generator updates the prompt
3. **Criteria:**
   - Coverage: recall against golden set entities
   - Precision: no false positives
   - Format compliance: valid JSON matching output contract

**Output:** A versioned extraction spec file that Haiku can execute cheaply.

**This is Phase 2 from the extraction pipeline experiments.** Validated: Haiku with simmered spec achieved 6.1/10 composite, zero hallucinations.

## Step 5: Domain-Specific Re-Extraction

**Model:** Haiku with simmered spec

**Process:**
1. Run spec against all documents in the domain
2. Per-document: chunk → extract → deduplicate within-document
3. Entity normalization cascade on new entities
4. Merge into graph — additive, doesn't remove first-pass entities
5. Tag entities with domain, spec version, extraction pass

**Provenance:** Each entity tracks:
- Source document
- Chunk reference (for citation)
- Extraction pass (first-pass generic vs domain-specific)
- Spec version

## Step 6: Visualization

**The cosmic visualization from the existing docs:**
- Domains as nebulae (positioned via UMAP)
- Entities as stars (positioned by attraction to domain centroids)
- Trade routes between domains sharing entities
- Documents as comets during ingest

**Updated after each pipeline step.** The graph grows incrementally — first-pass extraction populates it immediately, domain-specific extraction enriches it.

## Normalization — Unified Pattern

Both domain normalization and entity normalization use the same cascade:

```
1. String rules (cheap, deterministic)
   → lowercase, strip, punctuation, plural collapse

2. Embedding clustering (scalable)
   → all-MiniLM-L6-v2, cosine similarity, agglomerative clustering

3. LLM review (accurate, ambiguous tail only)
   → model confirms or rejects merges for clusters where
     embedding similarity is high but semantic meaning may differ
   → "dark beige" ≠ "light beige" despite high similarity
   → "3d printer" (tool) ≠ "3d printing" (technique)

4. Canonical name selection
   → highest frequency member of cluster wins
   → not LLM-chosen (ensures consistency across runs)

5. Merge map storage
   → persist merge decisions so they're not re-made
   → new entities check against merge map before insertion
```

**When does normalization run?**
- After first-pass extraction (entities)
- After domain classification (domains)
- After domain-specific re-extraction (entities)
- Periodically as corpus grows (batch normalization, catches new clusters)

## Simmer Integration

All "simmering" steps use the simmer-sdk:

```python
from simmer_sdk import refine

# Golden set simmering (Step 3)
golden_result = await refine(
    artifact=golden_set_path,
    evaluator="python score_golden_set.py --docs {candidate_path}",
    criteria={
        "coverage": "captures everything a domain expert would want",
        "precision": "no noise or hallucinated entities",
        "taxonomy_quality": "entity types are meaningful and consistent",
    },
    primary="coverage",
    iterations=5,
    judge_mode="board",
)

# Extraction spec simmering (Step 4)
spec_result = await refine(
    artifact=spec_template_path,
    evaluator="python score_extraction.py --spec {candidate_path} --golden {golden_set_path}",
    criteria={
        "coverage": "recall against golden set entities",
        "precision": "zero false positives",
        "format_compliance": "valid JSON matching output contract",
    },
    primary="coverage",
    iterations=5,
    judge_mode="board",
)
```

## Data Model

### Document

```
id: uuid
title: str
source_path: str (file path, URL, etc.)
content: str
domains: list[str] (domain paths)
extraction_passes: list[{pass_type, spec_version, timestamp}]
chunks: list[{offset, length, text}]
```

### Entity

```
id: uuid
canonical_name: str
type: str (from domain taxonomy)
domains: list[str]
sources: list[{document_id, chunk_ref, extraction_pass}]
merge_history: list[str] (names that merged into this)
```

### Domain

```
path: str (hierarchical, e.g., "techniques/wet-blending")
parent: str (parent domain path)
document_count: int
spec_version: int (null if no simmered spec)
spec_created_at: timestamp
entity_types: list[str] (from golden set)
merge_map: dict (normalized name → canonical)
```

### Relationship

```
from_entity: uuid
to_entity: uuid
type: str (domain-specific or generic)
weight: float
source_documents: list[uuid]
```

## What's Already Built and Validated

| Component | Status | Where |
|-----------|--------|-------|
| Extraction pipeline (3-phase) | Validated on 20 tutorials | docs/extraction-pipeline/ |
| Domain classification | Validated, 32 domains | docs/domain-classification/ |
| Entity normalization cascade | Validated at scale (14K → 12K) | docs/extraction-pipeline/warhammer-pipeline-learnings.md |
| Search & retrieval (4-path hybrid) | Running at spark:7870 | docs/search-retrieval/ |
| Tutorial RAG pipeline | Running at spark:7870 | docs/tutorial-rag/ |
| Cosmic visualization | Running at spark:7860 | docs/cosmic-visualization/ |
| Simmer SDK | Working, tested on DND + extraction | /Users/michaelsugimura/Documents/GitHub/simmer-sdk/ |

## What Needs to Be Built

| Component | Priority | Effort |
|-----------|----------|--------|
| Ingest page (upload UI) | High | Medium |
| Pipeline orchestrator (watches domains, triggers simmering) | High | Medium |
| Generic first-pass spec (people/places/things/ideas/actions) | High | Low |
| Golden set scorer (evaluator for Step 3) | High | Medium |
| Extraction spec scorer (evaluator for Step 4) | High | Low (exists from experiments) |
| Spec templating (golden set → extraction spec files) | Medium | Low |
| Domain taxonomy storage + merge map persistence | Medium | Medium |
| Viz page integration (update cosmic viz from pipeline) | Medium | Low (viz exists) |
| Search page | Low | Low (RAG exists) |

## Open Questions

1. **How many docs to sample for golden set?** The experiment used 20. Is that enough for a broad corpus, or do we need more for diverse domains?

2. **When to re-simmer?** Time-based? Count-based? Quality degradation signals? The experiment didn't test re-simmering triggers.

3. **Multi-domain documents** — a document about "color theory for miniature painters" belongs to both `theory/color-theory` and `techniques/`. Extract through both specs? Or just the primary domain?

4. **User feedback loop** — can users flag bad entities or missing entities in the viz? If so, does that feedback flow back into the next simmering round?

5. **Incremental normalization** — when a new entity arrives, do we re-run the full cascade or just check the merge map + embed + compare to nearest cluster?
