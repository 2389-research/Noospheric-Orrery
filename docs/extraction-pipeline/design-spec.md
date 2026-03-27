# Adaptive Knowledge Graph Extraction System

**Date:** 2026-03-24
**Status:** Draft
**Authors:** Michael Sugimura, Claude

## Problem Statement

Building a knowledge graph from arbitrary content requires entity extraction that works across domains without hand-crafted prompts or predefined schemas. Current approaches either use static extraction prompts (infodesk) or require domain experts to author extraction configurations (warhammer pipeline). Neither scales to a system where users dump emails, transcripts, hobby content, research papers, and business documents into the same graph.

The core challenge: **how do you extract high-quality, domain-appropriate entities from content you didn't anticipate, and get better at it over time, without human intervention?**

## Design Principles

1. **The graph is both output and context.** The graph's accumulated structure informs future extraction — domains, entity types, and relationships emerge from the data.
2. **Extraction specs are the artifact that improves, not the code.** The pipeline stays the same; what changes is the domain-specific instructions it operates with.
3. **Expensive work is amortized.** Domain classification and spec simmering are costly but happen once per document or once per domain. Per-document extraction with a finished spec is cheap.
4. **Queryable from moment one.** Every document produces rough entities immediately via lightweight NER. Domain-specific richness comes later.
5. **Multiple extraction passes are additive.** A document can be extracted through multiple domain specs at different levels of specificity, producing progressively richer graph content.

## System Overview

```
Document arrives
    │
    ├─ Operation A: Domain Classification (large model, expensive)
    │   → Assigns top-level domain + suggested subdomains
    │   → Uses existing domain taxonomy as context
    │
    ├─ Operation B: Lightweight Entity Extraction (NER/spaCy, cheap)
    │   → Named entities, co-occurrence edges
    │   → Immediately queryable in graph
    │
    ▼
Domain Registry
    │
    ├─ Domain count < threshold → document waits with rough entities
    │
    ├─ Domain count crosses threshold (N=100 default)
    │   │
    │   ▼
    │   Spec Simmering (iterative refinement loop)
    │   → Examines sample documents from domain
    │   → Researches domain via web search + existing graph
    │   → Proposes extraction spec
    │   → Evaluates against held-out documents
    │   → Iterates until quality plateaus
    │   → Outputs versioned extraction spec
    │   │
    │   ▼
    │   Batch Extraction
    │   → Runs spec against all documents in domain
    │   → Rich, domain-specific entities added to graph
    │   → Normalization pass (embed → cluster → reconcile)
    │
    ├─ New document arrives in domain with existing spec
    │   → Extracted immediately using current spec version
    │
    ├─ Subdomain crosses its own threshold
    │   → Gets its own simmered spec
    │   → Documents extracted through both parent + subdomain specs
    │
    └─ Re-simmering trigger (time-based, count-based, manual)
        → Spec re-simmered with larger/updated corpus
        → All documents in domain re-extracted with new spec version
```

## Detailed Design

### 1. Ingest: Two Parallel Operations

When a document arrives, two operations run (potentially in parallel):

#### Operation A: Domain Classification

- **Model:** Large, capable model (e.g., Claude Sonnet, GPT-4 class). This is the most important classification in the system and accuracy matters more than cost.
- **Input:** The document content + the current domain taxonomy (what domains exist, approximate sizes).
- **Output:**
  - Primary domain path (e.g., `hobby/miniature-painting`)
  - Suggested subdomains (e.g., `hobby/miniature-painting/airbrush-techniques`, `hobby/miniature-painting/nmm`)
  - Secondary domain paths if the document spans domains (e.g., a video about running a painting commission business → `hobby/miniature-painting` + `business/freelance`)
- **Subdomain suggestions are tentative.** They inform the domain registry but don't trigger spec creation on their own. Subdomains get refined when the parent domain's spec is simmered, or when enough content accumulates to warrant promotion to a full domain.
- **The classifier can propose new domains** not yet in the taxonomy. These get added to the registry as new branches.

#### Operation B: Lightweight Entity Extraction

- **Model:** Cheapest available option — local NER model (spaCy), small local LLM, or cheap hosted model. The specific technology doesn't matter; the goal is speed and immediate queryability.
- **Input:** The document content.
- **Output:**
  - Named entities (people, places, organizations, dates, products) with types from standard NER categories
  - Co-occurrence edges between entities appearing in the same document (weighted by proximity/frequency)
  - Source provenance (which document each entity was extracted from)
- **Purpose:** Makes the document immediately queryable in the graph. These are rough entities — "Duncan Rhodes" gets extracted as a Person, but "two thin coats" does not get recognized as a technique. That's fine; domain-specific extraction handles the rest later.
- **Entities from this pass are tagged as `extraction_pass: "rough"` so they can be distinguished from domain-specific extractions.**

### 2. Domain Registry

A lightweight data store tracking:

| Field | Description |
|-------|-------------|
| `domain_path` | Hierarchical path (e.g., `hobby/miniature-painting/nmm`) |
| `parent` | Parent domain path (e.g., `hobby/miniature-painting`) |
| `document_count` | Number of documents classified into this domain |
| `document_ids` | References to documents in this domain |
| `spec_version` | Current extraction spec version (null if none) |
| `spec_created_at` | When the current spec was simmered |
| `spec_doc_count` | How many documents the current spec was built from |
| `threshold` | Document count that triggers spec creation (default: 100) |
| `status` | `accumulating`, `simmering`, `active`, `re-simmering` |

**Trigger logic:**
- When `document_count` crosses `threshold` and `spec_version` is null → trigger initial spec simmering
- Re-simmering can be triggered by: manual request, time elapsed since last simmer, document count reaching some multiple of the original threshold (e.g., 5x), or quality degradation signals
- Subdomain promotion: when a subdomain crosses its own threshold, it becomes eligible for its own spec independent of the parent

**The registry is bookkeeping.** The exact trigger mechanisms are configurable and not architecturally significant. What matters is the concept: domains accumulate, thresholds trigger spec creation, and periodically you re-simmer and backfill.

### 3. Spec Simmering

The core innovation. When a domain crosses threshold, an iterative refinement loop builds a domain-specific extraction spec.

#### What is an extraction spec?

A complete extraction configuration for a domain, containing:

```yaml
domain: hobby/miniature-painting
version: 1
created_at: 2026-03-24
simmered_from_docs: 100

# Entity types to extract in this domain
entity_types:
  - technique    # painting methods (stippling, drybrushing, wet blending)
  - paint        # specific paint products (Mournfang Brown, Leadbelcher)
  - paint_brand  # manufacturers (Citadel, Vallejo, Scale75)
  - color        # color references (warm red, cold blue-grey)
  - tool         # physical tools (size 0 brush, airbrush, palette)
  - medium       # additives (flow improver, contrast medium)
  - model        # specific miniatures (Intercessor, Daemon Prince)
  - faction      # armies/groups (Space Marines, Skaven)
  - concept      # painting theory (color temperature, value contrast)
  - body_area    # parts of miniatures (shoulder pad, cloak, base)
  - person       # painters, creators (Duncan Rhodes, Squidmar)
  # ... discovered by simmering, not predefined

# Relationship types for this domain
relationship_types:
  - uses_technique   # person/tutorial → technique
  - applies_paint    # technique/step → paint product
  - paints_on        # technique → body_area
  - requires_tool    # technique → tool
  - mixes_with       # paint/medium → paint/medium
  - prerequisite_of  # technique/concept → technique/concept
  - belongs_to       # model → faction
  - demonstrates     # person → technique/concept
  # ... discovered by simmering, not predefined

# What to ignore
ignore_patterns:
  - YouTube metadata (subscriber counts, like buttons)
  - Room/studio setup
  - Sponsor segments
  - Generic single words without domain context

# Extraction guidance
extraction_notes: |
  Painting theory concepts are high-priority. Extract "color temperature"
  as a concept when the speaker explains WHY warm/cool matters, not when
  they just say "warm color."

  Transcript garbling is common for paint names. "Mour fang brown" and
  "mournfang brown" are the same paint.

# Few-shot examples (generated during simmering from actual documents)
examples:
  - input: "so I'm going to stipple on some highlights using a lighter mix..."
    entities:
      - {name: "stippling", type: "technique"}
      - {name: "highlighting", type: "technique"}
    relationships:
      - {from: "stippling", to: "highlighting", type: "prerequisite_of"}

# Processing configuration
chunking:
  strategy: "time-window"  # or "token-count", "paragraph", "none"
  window: "5m"
  overlap: "30s"

# Extraction is two-pass: entities first, then relationships
extraction_passes:
  - entities   # Pass 1: extract entities only
  - relationships  # Pass 2: extract relationships given entity list

# Normalization configuration for this domain
normalization:
  known_garbling:
    - ["mour fang brown", "mournfang brown"]
    - ["agrax earth shade", "agrax earthshade"]
    - ["squid more miniatures", "squidmar miniatures"]
  merge_rules: |
    Color shades are distinct entities (dark beige ≠ light beige).
    Brand names are distinct from product names (artist opus ≠ artist opus one).
    Tool names are distinct from activity names (3d printer ≠ 3d printing).
  embedding_model: "all-MiniLM-L6-v2"
  cluster_threshold: 0.15

# Target model for execution
execution_model: "qwen3.5:27b"  # cheap model that runs the spec
```

#### The simmering process

The simmering loop follows the simmer skill's architecture: **generate → evaluate → judge → reflect**, with strict context discipline between roles.

**Roles:**

| Role | Receives | Does NOT Receive |
|------|----------|------------------|
| **Generator** | Current spec, ASI (one focused direction from judge), domain research, background constraints | Scores, previous specs, evaluator output |
| **Evaluator** | Current spec, held-out documents, execution model | Everything else (it just runs the spec and produces output) |
| **Judge** | Extraction output, source documents, seed spec + seed scores, evaluator output, iteration history | Previous judges' ASI, intermediate scores |
| **Reflect** | Full score history, trajectory, search space | Candidate content |

**Loop structure:**

1. **Seed (iteration 0):**
   - **Generator** examines a representative sample of documents from the domain. It researches the domain via web search if needed. It proposes an initial extraction spec — entity types, relationship types, ignore patterns, chunking strategy, extraction guidance, few-shot examples.
   - **Evaluator** runs the spec (via a cheap execution model) against a held-out evaluation set.
   - **Judge** scores the extraction output. Investigation-first: the judge reads the actual source documents, reads the extraction output, and compares them. It scores on criteria (coverage, precision, domain-appropriateness, entity coherence, cross-document consistency). It produces one focused ASI — a single direction for improvement.

2. **Iterations 1-N:**
   - **Generator** receives only the ASI from the previous judge (not scores). It modifies the spec in that one direction.
   - **Evaluator** runs the updated spec against the held-out set.
   - **Judge** scores the new extraction. It sees the current output + source documents + seed scores as calibration reference. It does NOT see intermediate iteration scores (prevents anchoring). It produces a new ASI.
   - **Reflect** records the trajectory, tracks best-so-far, detects regressions. If this iteration regressed, the next generator receives the best spec (not the latest).

3. **Repeat** until quality plateaus (typically 3-5 iterations).

**Judge evaluation criteria:**
- **Coverage:** Are we capturing the important entities from the source material?
- **Precision:** Are we extracting noise or hallucinating entities not in the source?
- **Domain-appropriateness:** Are the entity types and relationship types meaningful for this domain?
- **Entity coherence:** Do the extracted entities form a sensible domain picture?
- **Cross-document consistency:** Are the same concepts extracted consistently across documents?

**Investigation-first judging:** The judge doesn't evaluate extraction quality in the abstract. It reads the source documents, understands what's actually in them, and compares that to what was extracted. It can use web search to research the domain — understanding what experts would consider important entities. This grounds judgment in evidence, not in the judge's prior beliefs about what "good extraction" looks like.

**Judge board (for complex domains):** For domains where a single judge's blind spots might limit quality, use a 3-judge board:
- Each judge scores from a different lens (e.g., "domain coverage analyst," "noise/precision analyst," "downstream query usefulness analyst")
- Judges score independently, then see each other's scores (not ASI) in one deliberation round
- A synthesis step distills all three judges' ASI candidates into one focused direction
- Output format is identical to single judge — the generator can't tell the difference

**Output:** A versioned extraction spec file + trajectory documenting score progression across iterations.

**Key insight:** The expensive reasoning (understanding the domain, evaluating quality, proposing improvements) happens once during simmering. The cheap model (execution model) runs the resulting spec on every document. This is the same pattern as training a model vs running inference — you spend compute once to build something that runs cheaply forever.

### 4. Domain-Specific Extraction

Once a spec exists, extraction happens per-document in **two passes**:

#### Pass 1: Entity Extraction

1. **Chunk** the document according to the spec's chunking strategy
2. **Extract entities** using the execution model + spec (entity types, guidance, few-shot examples)
3. **Deduplicate** within-document: merge on `name.lower().strip()`, keep first occurrence's type
4. **Tag** extracted entities with `extraction_pass: "domain"`, `domain: "hobby/miniature-painting"`, `spec_version: 1`
5. **Add to graph**

#### Pass 2: Relationship Extraction (separate prompt)

1. **Input:** The extracted entity list from Pass 1 + the source document chunks
2. **Extract relationships** between the identified entities using the spec's `relationship_types`
3. **Tag** relationships with domain and spec version

**Why two passes:** Empirical evidence from the warhammer pipeline shows that combining entity and relationship extraction in a single prompt degrades entity quality. The extraction model has limited attention — asking it to do both at once means it does both worse. Separating them keeps each pass focused. The relationship extractor also benefits from receiving a clean entity list, so it's extracting connections between known entities rather than discovering entities and connections simultaneously. This matches the iText2KG pattern.

#### Provenance

Each extracted entity and relationship tracks:
- **Document ID** — which source document
- **Chunk reference** — which chunk within the document (offset, timestamp, or section)
- **Extraction pass** — rough, domain (with domain path + spec version), or subdomain
- **Spec version** — which version of the domain spec produced this extraction

Chunk-level provenance is critical for downstream citation. When an agent retrieves an entity, it should be able to point back to the exact section of the source document.

#### Multi-spec extraction

When a document belongs to multiple domains that each have specs, it gets extracted through each relevant spec. A video about "color theory for miniature painters" might be extracted through:
- `hobby/miniature-painting` spec → extracts painting-specific entities (techniques, paints, models)
- `art/color-theory` spec → extracts art theory entities (color wheel relationships, complementary colors, value scales)

These are additive. The graph gets richer with each pass.

### 5. Normalization

Normalization happens at two levels, and the normalization configuration is itself a domain artifact.

#### Per-extraction normalization (inline)
- Basic string normalization (case, whitespace, punctuation)
- Plural collapse (only when both forms exist in corpus)
- Known garbling corrections from the spec's `normalization_hints` (see below)
- Applied during extraction

#### Domain-level normalization (batch, periodic)
After extraction across a domain's documents:
1. **Embed** all entities in the domain using a sentence embedding model (note: model selection matters — `all-MiniLM-L6-v2` works well for short domain terms; SigLIP2 and similar vision-language models perform poorly on short text)
2. **Cluster** similar entities (agglomerative clustering, cosine distance, threshold ~0.15)
3. **Reconcile** clusters — a model reviews each multi-member cluster and decides which members are the same entity, picks canonical names (highest-count member wins, not LLM choice — ensures consistency)
4. **Apply** normalization map across the domain

This is the same cascade proven in the warhammer pipeline: rule-based (cheap) → embedding-based (scalable) → model-based (accurate, only for ambiguous cases). Results from that pipeline: 14,033 unique raw names → 12,159 normalized (13.4% reduction via 919 plural merges + 1,151 cluster renames).

#### The cluster review prompt is a domain artifact

**Critical insight from the warhammer pipeline:** What constitutes a valid merge is domain-specific. The cluster review prompt must encode domain knowledge:
- `"dark beige" ≠ "light beige"` — different color shades (miniature painting)
- `"3d printer" (tool) ≠ "3d printing" (assembly technique)` — tool vs activity
- `"artist opus" (brand) ≠ "artist opus one" (specific brush)` — brand vs product
- `"almost black" ≠ "almost white"` — embedding similarity doesn't mean semantic equivalence

The cluster review prompt should be **simmered alongside the extraction spec** — it's part of the domain's extraction configuration. The spec gains a `normalization_hints` section:

```yaml
normalization_hints:
  known_garbling:
    - "mour fang brown" → "mournfang brown"
    - "agrax earth shade" → "agrax earthshade"
  merge_rules: |
    Color shades are distinct entities (dark beige ≠ light beige).
    Brand names are distinct from product names.
    Tool names are distinct from activity names.
  embedding_model: "all-MiniLM-L6-v2"
  cluster_threshold: 0.15
```

#### Cross-domain normalization
If `hobby/miniature-painting` and `art/color-theory` both have a "color temperature" entity, cross-domain normalization ensures they merge to the same node. This uses the same embed → cluster → reconcile cascade but runs across domain boundaries.

### 6. Graph Structure

Entities in the graph carry:

| Field | Description |
|-------|-------------|
| `id` | Canonical identifier (slug) |
| `type` | Entity type (domain-specific, e.g., `technique`, `concept`) |
| `name` | Human-readable canonical name |
| `properties` | Arbitrary key-value metadata (role, description, url, etc.) |
| `domains` | Which domains this entity belongs to |
| `extraction_passes` | Which extraction passes produced this entity (`rough`, `domain:hobby/miniature-painting:v1`) |
| `sources` | Provenance: document ID + chunk reference (offset/timestamp/section) per extraction |

Edges carry:

| Field | Description |
|-------|-------------|
| `type` | Relationship type — domain-specific (e.g., `uses_technique`, `applies_paint`) or generic (`related_to`, `mentioned_in`, `part_of`) |
| `weight` | Strength of association (co-occurrence count, extraction confidence, number of source documents) |
| `context` | Why these entities are linked (co-occurrence, same document, explicit extraction) |
| `source_documents` | Which documents established this connection |
| `temporal` | Timestamps from source material (when this relationship was observed/valid) |

**Edge philosophy:** Two types of edges coexist:
- **Rough edges** (from the lightweight first pass): co-occurrence links with weights. No type beyond `co_occurs`. These provide immediate graph connectivity.
- **Domain edges** (from domain-specific extraction): typed relationships defined by the domain's simmered spec. The miniature painting spec might define `uses_technique`, `applies_paint`, `paints_on`. The business spec might define `works_at`, `reports_to`, `manages`.

Relationship types are **per-domain, not global.** Each simmered spec defines the relationship vocabulary for its domain. Cross-domain relationships use a small generic set (`related_to`, `mentioned_in`, `part_of`). This avoids the vocabulary drift problem (no global taxonomy to keep consistent) while giving domains rich, meaningful edges for traversal.

Factual attributes (founded_by, role, title) live as **node properties**, not edge types. An edge that exists only to answer "who founded X" is really a queryable property on the node, not a connection you traverse.

### 7. Domain Lifecycle

```
New Domain Proposed (by classifier)
    │
    ▼
Accumulating (document_count < threshold)
    │ Documents get NER extraction only
    │ Domain taxonomy visible but no spec
    │
    ▼ [threshold crossed]

Simmering (spec being created)
    │ Iterative refinement loop running
    │ New documents still get NER extraction
    │
    ▼ [spec complete]

Active (spec exists, extraction running)
    │ New documents extracted via spec on arrival
    │ Batch extraction run on backlog
    │ Normalization applied
    │
    ├─► Subdomain promoted (subdomain crosses threshold)
    │   │ Subdomain gets its own simmering
    │   │ Documents in subdomain extracted through both specs
    │
    ├─► Re-simmering triggered (time, count, manual)
    │   │ Spec re-simmered with larger corpus
    │   │ All documents re-extracted with new spec version
    │   │ Old domain-specific entities replaced
    │
    └─► Domain split (domain grows too broad)
        │ Subdomains promoted, parent becomes organizational only
```

### 8. Subdomain Evolution

Subdomains emerge naturally:

1. **Early stage:** Classifier suggests subdomains as tags on documents. These are tentative — just metadata.
2. **Parent spec stage:** When the parent domain gets a spec, the simmering process may validate or refine subdomain boundaries based on what it sees in the content.
3. **Promotion stage:** When a subdomain accumulates enough content, it gets its own spec. This spec is more specialized — it extracts entities that the parent spec would miss or lump together.

**Example trajectory:**
- Documents about Warhammer hobby videos arrive. Classified as `hobby/miniature-painting`.
- At N=100, `hobby/miniature-painting` gets a spec. Extracts techniques, paints, models, concepts.
- Over time, 40 of those documents are specifically about airbrush work. Suggested subdomain: `hobby/miniature-painting/airbrush`.
- At N=100 airbrush-specific documents (or whatever threshold), `hobby/miniature-painting/airbrush` gets its own spec.
- The airbrush spec extracts things the parent misses: PSI settings, needle sizes, paint-to-thinner ratios, specific airbrush models, compressor types.
- A document about "airbrushing zenithal highlights on a Knight" now gets extracted through both specs — broad painting entities from the parent, detailed airbrush entities from the subdomain.

### 9. Cost Model

All operations can run on local/free models if desired. The cost model is about **quality tradeoffs**, not dollars.

| Operation | Model | Frequency |
|-----------|-------|-----------|
| Domain classification | Large model (quality matters most here) | Once per document |
| Rough extraction | Cheapest/fastest available (local NER, small LLM) | Once per document |
| Spec simmering | Large model for generator/judge, cheap model as execution target | Once per domain per version |
| Domain-specific extraction | Cheap/local model running the simmered spec | Once per document per spec version |
| Normalization (embed + cluster) | Local embedding model | Per domain, periodic |
| Normalization (model reconciliation) | Cheap/local model | Per domain, periodic |

**The key insight is quality, not cost.** A domain-specific spec on a cheap model produces better extraction than a generic prompt on an expensive model. The simmering loop encodes domain knowledge into the spec — the execution model doesn't need to understand the domain, it just follows detailed instructions. This is the same pattern as training vs inference.

**The entire pipeline can run for free** using local models (qwen3.5:27b, llama, etc.) and local embeddings. The tradeoff is purely: how much quality do you want at each stage, and how much compute time are you willing to spend on simmering?

## Empirical Validation: Warhammer Pipeline

The warhammer pipeline (`DS-scratch/warhammer_mini_sizes/`) is a manually-constructed instance of this design, providing empirical evidence for key assumptions. Full learnings documented in `docs/warhammer-pipeline-learnings.md`.

### Key findings that validate the design

1. **Prompt quality > model quality.** V1→V4 prompt evolution on the same qwen3.5:27b model produced a larger quality jump (5.3→8.25/10) than upgrading model size. This directly validates that simmered specs on cheap models outperform generic prompts on expensive models.

2. **Taxonomy emerges iteratively, not upfront.** The 18-type taxonomy was discovered over 4 prompt versions — V1 had ~10 types, each iteration added types after noticing what was being missed or mis-categorized. This is exactly what the simmering loop automates.

3. **The normalization cascade works at scale.** 14,033 → 12,159 unique entities (13.4% reduction). Each tier catches different things: rules catch plurals, embeddings catch garbling, LLM review catches context-dependent merges. Domain-specific merge rules are critical (what NOT to merge matters as much as what to merge).

4. **Transcript garbling is domain-specific and requires embed+LLM.** Edit distance doesn't catch it ("fist on red" → "mephiston red"). Only embedding similarity + LLM review handles domain-specific garbling patterns.

5. **Relationship extraction should be a separate pass.** Adding relationships to the entity extraction prompt degrades entity quality. The extraction model has limited attention — keeping each pass focused produces better results.

6. **Long-tail entity types are high-value.** `award` (398 mentions) and `skill_level` (253 mentions) are rare but valuable for queries. Don't prune types just because they're infrequent.

### Available ground truth for testing

- 659 fully extracted + normalized videos with known-good entity sets
- 3 test videos with Sonnet-grade ground truth extractions
- 12 hand-labeled normalization clusters
- Simmer trajectories documenting score progression for extraction and cluster review prompts

### Retrieval note: query expansion is mandatory

Single queries fail dramatically on domain abbreviations. "Painting NMM steel" → 0 relevant chunks. Expanded to 6 sub-queries → 4 chunks from the definitive tutorial. This is a retrieval concern (not extraction), but it affects how useful the graph is downstream. Any agent querying the graph needs query expansion — fan out 4-6 sub-queries in parallel, dedupe, re-rank.

## Relationship to Existing Work

### Infodesk (current)
Infodesk provides the runtime infrastructure: event sourcing, graph storage, WebSocket updates, MCP server, dashboard, interactive agent. The adaptive extraction system described here would replace infodesk's current single-pass metrics agent with the multi-stage pipeline. The rest of infodesk's architecture (event bus, graph storage, query agents, dashboard) remains valid and useful.

### Warhammer Pipeline
The warhammer pipeline is a manually-constructed instance of what this system automates. The 18-entity-type taxonomy, the chunking strategy, the normalization cascade — all of these were hand-crafted by examining the domain. This design automates that process: the simmering loop discovers entity types, chunking strategies, and normalization needs from the data itself.

### Simmer
The spec simmering process borrows simmer's core pattern: iterative refinement with investigation-first evaluation, focused single-direction improvement per iteration, and regression safety. The key adaptation is that the artifact being simmered is an extraction spec rather than a document or code file.

### Industry Patterns
- **AutoSchemaKG:** Closest to the schema-free extraction approach. Differs in that AutoSchemaKG uses unsupervised clustering for schema induction; this design uses agent-driven iterative refinement.
- **GraphRAG:** Community detection post-extraction for retrieval. Complementary — could be applied to the output of this system's extraction.
- **LazyGraphRAG:** The lightweight NER first pass is inspired by LazyGraphRAG's insight that NLP-level extraction + graph statistics is sufficient for immediate queryability.
- **iText2KG:** Multi-stage extraction pipeline. Similar architecture but with static extraction configuration rather than domain-adaptive specs.

## Open Questions

1. **Domain classification model selection.** What model is "good enough" for classification? Can this be a smaller model than initially assumed, given that misclassification is recoverable (documents can be reclassified)?

2. **Cross-domain entity resolution.** When the same entity appears in multiple domains (e.g., "color temperature" in both miniature painting and photography), how and when do we merge them? Same normalization cascade, or a separate cross-domain reconciliation step?

3. **Domain taxonomy governance.** As the taxonomy grows, who/what prevents it from becoming unwieldy? Is there a pruning mechanism for domains that stop receiving content? A merging mechanism for domains that overlap too much?

4. **Spec portability.** Can a spec simmered for one user's miniature painting content work for another user's miniature painting content? If specs are shareable, this becomes a marketplace/community problem.

5. **Graph versioning during re-extraction.** When a domain is re-extracted with a new spec version, how do we handle the transition? Replace all domain-specific entities atomically? Run old and new in parallel and diff?

6. **Simmering evaluation criteria weighting.** The judge evaluates on coverage, precision, domain-appropriateness, coherence, and consistency. How should these be weighted? Should the setup phase determine weights based on the domain characteristics (e.g., precision matters more for medical content, coverage matters more for exploratory research)?

## Research Context

This design was validated against current literature (as of March 2026):

- **Iterative prompt optimization for extraction is empirically validated.** IBM/VLDB 2025 showed DSPy, APE, and TextGrad consistently outperform human-written extraction prompts. Gains increase with schema complexity. (arxiv.org/abs/2506.19773)
- **The full loop (classify → accumulate → simmer → deploy) appears to be novel in combination.** Individual pieces exist: PARSE (Amazon) optimizes provided schemas; LOGOS does iterative codebook refinement; AutoSchemaKG does schema induction. None combine domain discovery + threshold triggers + agent-driven iterative refinement + cheap execution.
- **AutoSchemaKG** achieved 92-95% semantic alignment with human-crafted schemas from 50M documents, validating that schema-free extraction with post-hoc induction works. (arxiv.org/abs/2505.23628)
- **Multi-pass extraction is standard.** GraphRAG's "gleanings" (re-prompting "did you miss any entities?") significantly improves recall. iText2KG separates entity and relationship extraction into distinct passes.
- **Typed semantic relationships outperform co-occurrence for multi-hop reasoning** across GraphRAG benchmarks. Per-domain relationship vocabularies (defined by simmered specs) address vocabulary drift. (Zep/Graphiti, arxiv.org/abs/2501.13956)
- **Entity resolution has converged on a cascading pattern:** rule-based blocking (cheap) → embedding similarity (scalable) → model reasoning (expensive, ambiguous tail only). This matches the warhammer pipeline's proven approach. (iText2KG replaced LLM-based resolution with cosine similarity and saw ~31% improvement.)
