# Noospheric Orrery

An adaptive knowledge graph system that ingests documents, discovers domains, extracts structured entities, and surfaces them through a tutorial RAG pipeline and interactive cosmic visualization.

Built on miniature painting YouTube tutorials as the proof-of-concept domain. The system is domain-agnostic — the adaptive extraction pipeline discovers entity types, relationship types, and domain taxonomy from the data itself.

## System Overview

```
Documents (YouTube transcripts, articles, etc.)
    │
    ├── Domain Classification        →  Hierarchical topic taxonomy
    ├── Lightweight Entity Extraction →  Immediate rough entities (NER/spaCy)
    │
    ▼
Domain accumulates documents
    │
    ├── Threshold crossed
    │   ├── Simmer gold standard (quality benchmark)
    │   ├── Simmer extraction spec (domain-specific prompts)
    │   └── Batch extract all docs with simmered spec
    │
    ▼
Knowledge Graph
    ├── Entities (typed, normalized, cross-domain merged)
    ├── Relationships (co-occurrence + typed from simmered specs)
    └── Domain hierarchy (emergent from classification)
    │
    ▼
Applications
    ├── Tutorial RAG      →  Ask questions, get cited tutorials
    ├── Visual Search     →  Find miniature kits by image similarity
    ├── Concept Studio    →  Generate concept art + technique previews
    └── Cosmic Viz        →  Interactive galaxy map of the knowledge graph
```

## Components

| Component | Description | Docs |
|-----------|-------------|------|
| **Extraction Pipeline** | Adaptive entity extraction with domain-specific simmered specs | [docs/extraction-pipeline/](docs/extraction-pipeline/) |
| **Domain Classification** | Hierarchical topic taxonomy — generate, normalize, reclassify after simmering | [docs/domain-classification/](docs/domain-classification/) |
| **Search & Retrieval** | Hybrid search: FAISS per-type + BM25 + NetworkX graph + transcript chunks | [docs/search-retrieval/](docs/search-retrieval/) |
| **Tutorial RAG** | Query expansion → retrieve → synthesize → judge → refine pipeline | [docs/tutorial-rag/](docs/tutorial-rag/) |
| **Cosmic Visualization** | Galaxy map: domains as nebulae, entities as stars, UMAP layout | [docs/cosmic-visualization/](docs/cosmic-visualization/) |
| **Noospheric App** | Web application with Search, Studio, Learn tabs | [docs/noospheric-app/](docs/noospheric-app/) |

## Current State (2026-03-27)

**Corpus:** 659 videos enriched (V2, general spec), 20 videos enriched (V3, adaptive spec), 5,300+ being mined from 16 channels.

**Deployed:** Noospheric app at spark:7860, Tutorial RAG service at spark:7870.

**Domain taxonomy:** 32 domains (23 parent + 9 subdomains from V3 adaptive spec) across 6 top-level regions.

**Key finding:** Prompt quality > model quality. A simmered extraction spec on a cheap model (Haiku) outperforms a generic prompt on an expensive model. The simmering loop encodes domain knowledge into the spec — the execution model just follows detailed instructions.

## Design Principles

1. **The graph is both output and context.** Accumulated structure informs future extraction.
2. **Extraction specs are the artifact that improves, not the code.** Pipeline stays the same; specs evolve.
3. **Expensive work is amortized.** Domain classification + spec simmering happen once. Per-document extraction is cheap.
4. **Queryable from moment one.** Every document produces rough entities immediately. Domain-specific richness comes later.
5. **Domains emerge from classification, not clustering.** LLM classifier proposes + names + assigns. Community detection validates.

## Key References

- [Adaptive Knowledge Graph Extraction Design Spec](https://github.com/...) — Full system architecture
- [Warhammer Pipeline Learnings](docs/extraction-pipeline/warhammer-pipeline-learnings.md) — Empirical validation
- [Cosmic Viz Rendering Spec](docs/cosmic-visualization/) — Galaxy map visual design
- [Search System Guide](docs/search-retrieval/) — Hybrid retrieval architecture
