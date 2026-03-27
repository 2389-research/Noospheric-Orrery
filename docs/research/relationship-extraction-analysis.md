# Relationship Extraction in Knowledge Graphs: Research Analysis

**Date:** 2026-03-27
**Context:** Deciding how to handle relationships in the Noospheric Orrery extraction pipeline
**Recommendation:** Start with co-occurrence + lightweight types. Add rich typed extraction later if multi-hop reasoning demands it.

## The Question

When extracting a knowledge graph from documents, how should we handle relationships between entities? Three approaches exist:

1. **Typed relationships** — many specific types (works_at, uses_technique, preceded_by, part_of)
2. **Generic + metadata** — few types (related_to, co_occurs) with natural language descriptions
3. **Co-occurrence only** — statistical edges based on entities appearing in the same chunk

## What Production Systems Actually Do

### Microsoft GraphRAG — Schema-Free
Uses `RELATES_TO` edges with natural language descriptions embedded in the relationship. No formal type classification. The description captures context that would be lost in a type label.

Why they chose this: simpler to extract, fewer LLM errors, description captures nuance that a type label can't. A relationship described as "Duncan demonstrates wet blending technique on the cloak" carries more information than `demonstrates(Duncan, wet_blending)`.

Source: [GraphRAG Explained — Zilliz](https://medium.com/@zilliz_learn/graphrag-explained-enhancing-rag-with-knowledge-graphs-3312065f99e1)

### Zep/Graphiti — Typed + Temporal
Uses typed, all-caps relationships (WORKS_FOR, IS_FRIENDS_WITH) with bi-temporal metadata (valid_at, invalid_at). This is for agent memory where consistency and temporal tracking matter more than extraction scale.

Source: [Zep: A Temporal Knowledge Graph Architecture for Agent Memory](https://arxiv.org/abs/2501.13956)

### iText2KG — Incremental, Constraint-Based
Extracts relationships but enforces semantic uniqueness through cosine similarity matching. Types aren't primary — duplicate/synonym relationships are merged. Key constraint: all relationships must reference entities from the known entity list (prevents hallucination).

Source: [iText2KG: Incremental Knowledge Graphs Construction Using Large Language Models](https://arxiv.org/abs/2409.03284)

### Enterprise/Production Systems
Generally prefer 5-15 relationship types maximum. Financial graphs use ~7 types. Research knowledge graphs use ~10-12. Systems with 50+ types report degraded LLM extraction quality.

Source: [From LLMs to Knowledge Graphs: Building Production-Ready Graph Systems in 2025](https://medium.com/@claudiubranzan/from-llms-to-knowledge-graphs-building-production-ready-graph-systems-in-2025-2b4aff1ec99a)

## Do Typed Relationships Help Retrieval?

### When They Help
Multi-hop reasoning benefits from typed edges. 2025 research on multi-hop KGQA showed hybrid KG+Text RAG frameworks improved accuracy 16.6% on AdvHotpotQA by explicitly modeling relationship types during path planning. If you need to answer "who worked at the company that developed the technique used in this tutorial?" — typed edges enable that traversal.

Source: [How to Improve Multi-Hop Reasoning With Knowledge Graphs and LLMs — Neo4j](https://neo4j.com/blog/genai/knowledge-graph-llm-multi-hop-reasoning/)

### When They Don't Help
For single-hop retrieval (most RAG queries), co-occurrence edges with weight are sufficient. "What techniques are related to NMM?" doesn't need `uses_technique` vs `demonstrates` vs `teaches` — it just needs "these entities appear together frequently in the context of NMM."

Our tutorial RAG pipeline already returns good results using co-occurrence edges (1.3M edges in NetworkX) without typed relationships.

### The Quality Trade-off
Typed edges help downstream IF extraction quality is high. But type classification introduces a new error surface:
- The LLM might assign the wrong type (false typing)
- The same relationship gets different types in different documents (inconsistency)
- Edge cases don't fit any predefined type (forced classification)

Untyped descriptions are more robust — fuzzy matching on descriptions still finds relevant edges even if the description varies slightly between documents.

## Why Quality Degrades with Typed Extraction

### The Error Cascade

Entity extraction and relationship extraction compound errors:

1. **Entity extraction** has a known error rate. Our best simmered spec achieved 89% precision / 65% recall on entities. That means ~11% of entities are noise and ~35% are missed.

2. **Relationship extraction operates on that noisy entity set.** If entity A is a false positive and entity B is real, any relationship between them is automatically wrong. With 11% entity noise, roughly 20% of relationships involving those entities are invalid (11% chance either endpoint is wrong, compounded across both endpoints).

3. **Adding type classification on top** introduces a third error layer. Research shows LLMs extract the same relationship multiple ways — "works at", "employed by", "is employed at" all mean the same thing but get different type labels. Even with post-processing deduplication, type inconsistency is persistent.

Source: [LLM-empowered knowledge graph construction: A survey](https://arxiv.org/abs/2510.20345)

### Empirical Evidence from Our Testing

In the simmer extraction experiments, we spent 6 rounds of meta-testing plus 8+ individual runs refining entity extraction. The judge board, investigation-first flow, stable wins tracking, normalization cascade — all of that machinery was needed to get entity extraction to 89% precision.

Relationship extraction hasn't been through any of that refinement. Adding a typed relationship pass now would produce results comparable to our early entity extraction runs (before simmering) — noisy, inconsistent, and requiring significant iteration to improve. That iteration should happen after the entity pipeline is solid, not simultaneously.

### Scale Compounds the Problem

At our projected scale (1K-10K documents, 10K-100K entities):
- Expected relationship count: 1-2M (research finding)
- Expected duplication/hallucination rate: 10-20% even with entity constraint checks
- With 50+ relationship types, training data per type becomes sparse and LLM classification becomes unreliable
- With 5-7 types, classification stays consistent but most relationships end up as `related_to` anyway

Source: [Efficient Knowledge Graph Construction and Retrieval from Unstructured Text for Large-Scale RAG Systems](https://arxiv.org/html/2507.03226v2)

## The Schema-Free vs Schema-Based Landscape

Research from 2024-2025 shows a clear trend away from heavy ontologies toward hybrid approaches:

### Schema-Based (Typed) Approaches
- Use Competency Questions to define scope
- Build formal ontology with predefined types
- High consistency, machine-interpretable, Wikidata alignment
- Requires domain expertise to design the schema
- LLM makes type classification errors that compound

### Schema-Free Approaches
- Extract relationships as free text with optional confidence scores
- LLM infers structures through guided reasoning
- Flexible, covers unexpected relationships, fewer extraction errors
- Less structured, harder to validate, requires robust deduplication

### The 2025 Consensus
Lightweight post-processing constraints on schema-free extraction. Not heavy upfront ontology design, but also not pure free text. The constraint that matters most: **entities in relationships must come from the known entity list** (iText2KG's key finding).

Source: [Knowledge Graph Construction: Extraction, Learning, and Evaluation](https://www.mdpi.com/2076-3417/15/7/3727)

### RELATE Framework Finding
When researchers tested mapping free-text relations to predefined ontology predicates, they achieved 52% exact match and 94% accuracy@10 — but this required significant post-processing. Generic descriptions performed better without that overhead.

Source: [Relation Extraction with Fine-Tuned Large Language Models in Retrieval Augmented Generation Frameworks](https://arxiv.org/html/2406.14745v2)

## Recommendation for Noospheric Orrery

### V1: Co-occurrence + Lightweight Types

```
from_entity: uuid
to_entity: uuid
type: str        # one of: co_occurs, related_to, part_of, mentions
weight: float    # co-occurrence frequency or extraction confidence
source_chunk: ref
```

Four types:
- `co_occurs` — statistical, entities in same chunk (free, no LLM needed)
- `related_to` — generic LLM-extracted relationship (if we add pass 2)
- `part_of` — hierarchical (faction → game system, technique → category)
- `mentions` — document → entity provenance

Weight from co-occurrence frequency. This is what we already have working — the warhammer pipeline's 1.3M edges use this pattern and the search/RAG pipeline returns good results.

### Why This Is Enough for Now

1. **The visualization doesn't need typed edges.** Domains as nebulae, entities as stars, trade routes between domains sharing entities. Adding `uses_technique` vs `demonstrates` doesn't change the visual.

2. **The RAG pipeline works without typed edges.** Tutorial RAG returns good results using co-occurrence + chunk retrieval. Query expansion handles the retrieval quality — not relationship types.

3. **Entity extraction is where the value is.** The simmered spec pipeline (golden set → extraction spec → Haiku execution → normalization cascade) is proven and produces high-quality entities. Relationships are secondary — co-occurrence gets 80% of the way there for free.

4. **Simmer the things that matter most first.** Our testing showed that judge quality, investigation depth, and iterative refinement are what drive extraction quality. That machinery should be applied to entities first. Relationship extraction can be simmered later when there's a clear retrieval use case that demands it.

### V2 (When Needed): Type + Description Hybrid

If multi-hop reasoning or specific traversal queries become important:

```
from_entity: uuid
to_entity: uuid
type: str           # one of 5-10 lightweight types
description: str    # free-text natural language description
confidence: float
source_chunk: ref
```

Extraction prompt pattern (based on iText2KG + Zep):
```
Given these entities that exist in this document: [entity list]
And this text: [chunk]

Extract relationships between entities. For each:
1. Name both entities (must be from the list above — never invent entities)
2. Describe the relationship in one sentence
3. If it clearly fits a type, tag it: [RELATED_TO, PART_OF, USES, PRECEDES, LOCATED_AT]
   (leave blank if unclear)
```

Post-processing (mandatory):
1. Constraint: all entities must be from known entity list
2. Dedup: fuzzy match descriptions, merge semantically identical relationships
3. Type inference: for blank types, classify from description in a secondary pass

### V2 Trigger

Add rich relationship extraction when:
- Users need multi-hop queries ("who taught the technique used to paint this model?")
- The visualization needs edge semantics (edge types as visual channels)
- A downstream task explicitly fails because co-occurrence isn't enough

Don't add it speculatively. The entity extraction pipeline is the priority.

## Summary Table

| Approach | Extraction Quality | Retrieval Value | Implementation Cost | Our Recommendation |
|----------|-------------------|-----------------|--------------------|--------------------|
| Co-occurrence only | Perfect (statistical) | Good for single-hop | Zero (byproduct of extraction) | **V1 — start here** |
| 5-7 lightweight types | Good (LLM handles few types well) | Good + basic traversal | Low | **V1 — add these 4 types** |
| 15+ typed relationships | Degrades at scale | Better for multi-hop | High (needs simmering + normalization) | V2 — when needed |
| 50+ typed relationships | Poor (LLM can't classify consistently) | Diminishing returns | Very high | Never |
| Free-text descriptions | Good (robust to extraction variation) | Good with embedding search | Medium | V2 — add description column |

## References

- [GraphRAG Explained: Enhancing RAG with Knowledge Graphs](https://medium.com/@zilliz_learn/graphrag-explained-enhancing-rag-with-knowledge-graphs-3312065f99e1) — Microsoft's schema-free approach
- [Zep: A Temporal Knowledge Graph Architecture for Agent Memory](https://arxiv.org/abs/2501.13956) — typed + temporal for agent memory
- [iText2KG: Incremental Knowledge Graphs Construction](https://arxiv.org/abs/2409.03284) — entity constraint, semantic dedup
- [LLM-empowered knowledge graph construction: A survey](https://arxiv.org/abs/2510.20345) — schema-based vs schema-free comparison
- [How to Improve Multi-Hop Reasoning With Knowledge Graphs and LLMs](https://neo4j.com/blog/genai/knowledge-graph-llm-multi-hop-reasoning/) — 16.6% improvement from typed edges
- [Relation Extraction with Fine-Tuned LLMs in RAG Frameworks](https://arxiv.org/html/2406.14745v2) — RELATE framework, 52% exact match on ontology mapping
- [From LLMs to Knowledge Graphs: Production-Ready Graph Systems in 2025](https://medium.com/@claudiubranzan/from-llms-to-knowledge-graphs-building-production-ready-graph-systems-in-2025-2b4aff1ec99a) — enterprise type count recommendations
- [Knowledge Graph Construction: Extraction, Learning, and Evaluation](https://www.mdpi.com/2076-3417/15/7/3727) — hybrid approach trend
- [Efficient Knowledge Graph Construction and Retrieval for Large-Scale RAG Systems](https://arxiv.org/html/2507.03226v2) — scale considerations
- [Structured Entity Extraction Using Large Language Models](https://arxiv.org/html/2402.04437v3) — extraction quality patterns
- [Ontology RAG: Schema-Driven Knowledge Extraction](https://trustgraph.ai/guides/key-concepts/ontology-rag/) — ontology-constrained extraction
