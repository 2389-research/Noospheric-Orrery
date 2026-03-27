# Extraction Pipeline

The core of Noospheric Orrery — an adaptive, domain-discovering entity extraction system that automatically builds domain-specific extraction specs from raw content.

## How It Works

Documents go in, structured knowledge graph entities come out. The system gets smarter per-domain as content accumulates.

```
Documents arrive
    │
    ├─ Classify into domain (Sonnet)
    ├─ Lightweight entity extraction (Haiku, immediate)
    │
    ▼
Domain accumulates documents
    │
    ├─ Threshold crossed (N=100)
    │   │
    │   ├─ Phase 1: Simmer gold standard (~1.5h, ~$5-10)
    │   ├─ Phase 2: Simmer extraction spec (~1.5h, ~$5-10)
    │   └─ Phase 3: Batch extract all domain docs (Haiku, ~$0.05-0.10/doc)
    │
    ├─ New docs → extract with existing spec
    └─ Re-simmer periodically as domain grows
```

## Documents

| Document | Description |
|----------|-------------|
| [design-spec.md](design-spec.md) | Full system design — adaptive extraction, domain registry, spec simmering, graph structure |
| [pipeline-guide.md](pipeline-guide.md) | Proven pipeline from experiment — what works, what doesn't, model stack, lessons learned |
| [experiment-notes.md](experiment-notes.md) | Detailed experiment log — gold standard simmering, spec simmering (qwen + Haiku), qualitative analysis |
| [data-manifest.md](data-manifest.md) | File paths, JSON schemas, type taxonomy — reference for consuming extraction output |
| [warhammer-pipeline-learnings.md](warhammer-pipeline-learnings.md) | Empirical findings from the original hand-crafted warhammer extraction pipeline |

## Key Decisions

- **Sonnet for simmering, Haiku for extraction.** Haiku precision=7 vs qwen precision=2. Haiku follows restraint instructions well and costs ~$0.05-0.10 per document.
- **simmer-sdk drives the refinement loop.** Programmatic `refine()` API with judge board, regression detection, stable wins tracking.
- **Entity types are per-domain, discovered automatically.** No global taxonomy — each domain simmers its own types from the data.
- **Typed edges are per-domain too.** Relationship vocabularies come from simmered specs, not a global set.
- **Extraction is two-pass.** Entities first, relationships second (single pass degrades quality).

## Experiment Data

The pipeline was proven on miniature painting YouTube tutorials:
- 20 eval segments, 156 gold standard entities, 14 types
- Best spec scored 6.1/10 composite (Haiku execution)
- 228 entities extracted across 20 full tutorials
- Source data at: `/Users/michaelsugimura/Documents/GitHub/DS-scratch/warhammer_mini_sizes/experiments/adaptive-spec-simmering/`
