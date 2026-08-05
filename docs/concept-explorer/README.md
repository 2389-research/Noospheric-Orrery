# Concept Explorer

Given a search query, surface concepts worth investigating next — not facts already
sitting in the graph, but tensions, mismatches, and open questions implied by how the
matched entities, their domains, and their neighbors relate. This is the procedure used
manually (via `/search` and `/entities/{id}/cooccurrences`) to analyze repos like
NaVILA and LaViRA in the orrery, now exposed as a single endpoint.

## The pipeline

```text
query
  └─ resolve   ─▶ search_knowledge_graph(query)            top-matching entities
       └─ traverse ─▶ get_cooccurrences(entity_id) per hit  1-hop neighbors, weighted
            └─ domains  ─▶ entity_sources ⋈ document_domains  which domain(s) each entity lives in
                 └─ synthesize ─▶ one Relay.complete_structured call
                      └─ 3 concepts: {name, evidence}
```

One retrieval pass (entities only, no chunk text) + one LLM call. No background job —
this runs synchronously inside the request, same as `/search` itself.

## How each stage works

### 1. Resolve

Reuses `search_knowledge_graph` (the same 5-stage pipeline behind `/search`) to find
the entities matching the query. Only `result.entities` is used — chunk text is not
retrieved or passed downstream.

### 2. Traverse

For each of the top-matched entities (capped — `MAX_ENTITIES`), call the existing
`store.relationships.get_cooccurrences(entity_id, limit=...)` (the function backing
`GET /entities/{id}/cooccurrences`).

### 3. Domains

For each top-matched entity, join `entity_sources` → `document_domains` to get the
distinct domain paths its source documents belong to. This is the structural
"what area of the taxonomy is this entity part of" signal — deliberately not raw
source text, to keep the model working from graph structure rather than prose.

### 4. Synthesize

One `relay.complete_structured` call (pattern shared with `subdomain_discovery.py`),
model = `settings.classification_model`. The prompt lists each top entity with its
domains and weighted neighbors, and instructs the model to output exactly 3 concepts,
each framed as a gap or tension implied by that structure — not a tool/entity name
restated.

Schema: `{"concepts": [{"name": str, "evidence": str}, ...]}`, length 3.

## Endpoint

`GET /search/concepts?q=<query>` → `orchestrator/src/routes/search.py`

```json
{
  "query": "lavira",
  "concepts": [
    {"name": "...", "evidence": "..."},
    {"name": "...", "evidence": "..."},
    {"name": "...", "evidence": "..."}
  ]
}
```

Implementation: `orchestrator/src/pipeline/concept_explorer.py`.

## Deferred (not in v1)

- No chunk/source-text grounding — entities + domains + cooccurrences only.
- No caching/persistence of generated concepts — regenerated on every call.
- No dedicated env var for model choice — reuses `classification_model`.
- No frontend wiring yet (this doc + endpoint only).
