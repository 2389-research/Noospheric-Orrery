# Search Architecture Spec — Noospheric Orrery
## For Implementation by Code LLM

**Date:** 2026-03-28
**Status:** Ready for implementation
**Context:** This spec describes a search and retrieval system for a knowledge graph framework that handles arbitrary domains. The graph contains typed entities with rich attributes and lightweight edges. The system treats the graph as a structured search index, not a graph traversal engine.

---

## Design Philosophy

The graph is a set of searchable indexes. Entities are the primary search surface. Edges are metadata, not a query engine. Retrieval is search, not graph algorithms. An agentic loop handles multi-step reasoning. The LLM does synthesis, not the retrieval system.

This system must work across arbitrary domains (business graphs, gaming knowledge bases, etc.) using the same backend. No domain-specific assumptions in the retrieval layer.

---

## Architecture Overview

```
User/Agent Query
    │
    ▼
┌─────────────────────────────┐
│  STAGE 0: Query Expansion   │
│  (Agentic / LLM-based)      │
│  Input:  original query      │
│  Output: N sub-queries       │
└──────────────┬──────────────┘
               │
               ▼
     ┌─────────────────┐
     │  For each of N   │
     │  sub-queries:    │
     │                  │
     │  ┌─────────────┐ │
     │  │ STAGE 1:    │ │
     │  │ Parallel    │ │
     │  │ Retrieval   │ │
     │  └──────┬──────┘ │
     │         │        │
     │  ┌──────▼──────┐ │
     │  │ STAGE 2:    │ │
     │  │ Entity-Based│ │
     │  │ Chunk Boost │ │
     │  └──────┬──────┘ │
     │         │        │
     └─────────┼────────┘
               │
               ▼
┌─────────────────────────────┐
│  STAGE 3: Cross-Query       │
│  RRF Fusion + Dedup         │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│  STAGE 4: Summarization     │
│  (Compress, no filtering)   │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│  STAGE 5: Synthesis         │
│  (LLM answers the question) │
└─────────────────────────────┘
```

---

## Data Model (Reference)

The spec assumes these existing tables. Adapt field names to match actual schema.

```sql
-- Primary search surface
entities (
    id              INTEGER PRIMARY KEY,
    canonical_name  TEXT UNIQUE NOT NULL,
    entity_type     TEXT NOT NULL,
    description     TEXT,
    embedding       BLOB,           -- 384-dim, all-MiniLM-L6-v2
    source_count    INTEGER          -- number of source documents mentioning this entity
)

-- Evidence layer
chunks (
    id              INTEGER PRIMARY KEY,
    content         TEXT NOT NULL,
    document_id     INTEGER NOT NULL,
    embedding       BLOB             -- 384-dim, all-MiniLM-L6-v2
)

-- Join table: entities ↔ chunks
entity_sources (
    entity_id       INTEGER NOT NULL,
    chunk_id        INTEGER NOT NULL,
    FOREIGN KEY(entity_id) REFERENCES entities(id),
    FOREIGN KEY(chunk_id) REFERENCES chunks(id)
)

-- Lightweight edges with text descriptions
relationships (
    id                  INTEGER PRIMARY KEY,
    source_entity_id    INTEGER NOT NULL,
    target_entity_id    INTEGER NOT NULL,
    description         TEXT,        -- free-text: "funded", "co-founded with", etc.
    source_chunk_id     INTEGER,     -- chunk where this relationship was extracted from
    weight              REAL,        -- co-occurrence frequency or confidence
    FOREIGN KEY(source_entity_id) REFERENCES entities(id),
    FOREIGN KEY(target_entity_id) REFERENCES entities(id)
)

-- Source documents
documents (
    id              INTEGER PRIMARY KEY,
    title           TEXT NOT NULL,
    url             TEXT,
    source          TEXT,
    processed_date  TIMESTAMP
)
```

### FAISS Indexes

```
entity_index:   FAISS IndexFlatIP, 384-dim, indexed on entities.embedding
chunk_index:    FAISS IndexFlatIP, 384-dim, indexed on chunks.embedding
```

Both use all-MiniLM-L6-v2 for encoding. Inner product on L2-normalized vectors = cosine similarity.

---

## STAGE 0: Query Expansion

**Purpose:** Decompose a single user query into N sub-queries that cover different angles, synonyms, and related concepts. This replaces the need for graph traversal algorithms — the LLM understands intent better than PPR.

**When to use:** Always, unless the caller explicitly opts out (e.g., for simple entity lookups). This is the highest-leverage step in the pipeline.

**Implementation:** This is an LLM call, handled by the agent layer. The search system exposes a `search()` function that accepts a list of queries. The agent decides how many and what queries to run.

### Pseudo-algorithm

```python
def expand_query(original_query: str, model: str = "haiku") -> list[str]:
    """
    Agent-driven query expansion. Returns N sub-queries.

    The agent (or a lightweight LLM call) decomposes the query.
    This runs OUTSIDE the search system — the search system
    receives already-expanded queries.
    """
    prompt = f"""
    Given this search query, generate 3-5 sub-queries that would help
    find all relevant information. Include:
    - The original query (or a cleaned version)
    - Synonym variations
    - Related concepts that might appear in source documents
    - More specific versions of vague terms

    Query: {original_query}

    Return as a JSON array of strings. No explanation.
    """

    sub_queries = llm_call(prompt, model=model)
    return parse_json_array(sub_queries)


# Example:
# expand_query("Harper Reed fundraising")
# → [
#     "Harper Reed fundraising",
#     "Harper Reed investment funding seed round",
#     "Harper Reed venture capital investors",
#     "Harper Reed startup financing"
# ]
```

### Parameters

| Param | Default | Notes |
|-------|---------|-------|
| `model` | haiku | Cheap/fast model. Expansion doesn't need strong reasoning. |
| `max_sub_queries` | 5 | Cap to control downstream cost. |
| `temperature` | 0.7 | Some creativity helps synonym generation. |

### Cost/Latency

- ~500ms-1s per expansion call (Haiku)
- ~$0.0005 per call
- Can be skipped for programmatic/exact entity lookups

---

## STAGE 1: Parallel Retrieval (Per Sub-Query)

**Purpose:** For each sub-query, retrieve candidate entities and chunks from multiple signals in parallel.

**Three retrieval channels run concurrently:**

### Channel A: Semantic Entity Search (FAISS)

```python
def search_entities_semantic(query: str, top_k: int = 20) -> list[ScoredEntity]:
    """
    Embed query, search FAISS entity index.
    Returns entities ranked by cosine similarity.
    """
    query_embedding = embed(query)  # all-MiniLM-L6-v2, 384-dim

    distances, indices = entity_index.search(
        query_embedding.reshape(1, -1),
        k=top_k
    )

    results = []
    for rank, (dist, idx) in enumerate(zip(distances[0], indices[0])):
        entity = get_entity_by_faiss_index(idx)
        results.append(ScoredEntity(
            entity_id=entity.id,
            name=entity.canonical_name,
            entity_type=entity.entity_type,
            score=float(dist),  # cosine similarity
            rank=rank,
            source="semantic_entity"
        ))

    return results
```

### Channel B: Semantic Chunk Search (FAISS)

```python
def search_chunks_semantic(query: str, top_k: int = 20) -> list[ScoredChunk]:
    """
    Embed query, search FAISS chunk index.
    Returns chunks ranked by cosine similarity.
    """
    query_embedding = embed(query)

    distances, indices = chunk_index.search(
        query_embedding.reshape(1, -1),
        k=top_k
    )

    results = []
    for rank, (dist, idx) in enumerate(zip(distances[0], indices[0])):
        chunk = get_chunk_by_faiss_index(idx)
        results.append(ScoredChunk(
            chunk_id=chunk.id,
            content=chunk.content,
            document_id=chunk.document_id,
            score=float(dist),
            rank=rank,
            source="semantic_chunk"
        ))

    return results
```

### Channel C: Exact Match on Entity Names

```python
def search_entities_exact(query: str) -> list[ScoredEntity]:
    """
    Exact/substring match on entity canonical names.
    Handles the case where someone types 'betaworks' and we need
    to find the entity 'betaworks' with high confidence.

    At current scale (<10K entities), LIKE queries on SQLite are fine.
    Migrate to FTS5/BM25 when entity count exceeds ~10K.
    """
    # Normalize query
    query_lower = query.lower().strip()
    query_terms = query_lower.split()

    results = []

    # Exact full match (highest boost)
    exact = db.execute("""
        SELECT id, canonical_name, entity_type, description
        FROM entities
        WHERE LOWER(canonical_name) = ?
    """, [query_lower])

    for row in exact:
        results.append(ScoredEntity(
            entity_id=row.id,
            name=row.canonical_name,
            entity_type=row.entity_type,
            score=1.0,  # perfect match
            rank=0,
            source="exact_match"
        ))

    # Substring match (lower boost)
    for term in query_terms:
        if len(term) < 3:
            continue  # skip short terms to avoid noise

        partial = db.execute("""
            SELECT id, canonical_name, entity_type, description
            FROM entities
            WHERE LOWER(canonical_name) LIKE ?
            AND id NOT IN (?)
        """, [f"%{term}%", [r.entity_id for r in results]])

        for rank, row in enumerate(partial):
            results.append(ScoredEntity(
                entity_id=row.id,
                name=row.canonical_name,
                entity_type=row.entity_type,
                score=0.7,  # partial match
                rank=rank + len(results),
                source="exact_match"
            ))

    return results
```

### Parallel Execution

```python
def retrieve_for_subquery(query: str) -> SubQueryResults:
    """
    Run all three channels in parallel for a single sub-query.
    Returns combined results.
    """
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        future_entities = executor.submit(search_entities_semantic, query, top_k=20)
        future_chunks = executor.submit(search_chunks_semantic, query, top_k=20)
        future_exact = executor.submit(search_entities_exact, query)

    return SubQueryResults(
        query=query,
        semantic_entities=future_entities.result(),
        semantic_chunks=future_chunks.result(),
        exact_entities=future_exact.result()
    )
```

### Parameters

| Param | Default | Notes |
|-------|---------|-------|
| `entity_top_k` | 20 | Candidates per channel. Overretrieve, let fusion sort it out. |
| `chunk_top_k` | 20 | Same logic. |
| `exact_min_term_length` | 3 | Skip short words in LIKE queries. |
| `exact_match_boost` | 1.0 | Score for full exact match. |
| `partial_match_boost` | 0.7 | Score for substring match. |

### Latency

- FAISS search: ~5-20ms per index at current scale
- SQLite LIKE: ~1-5ms at current scale
- Total (parallel): ~20ms

---

## STAGE 2: Entity-Based Chunk Boosting

**Purpose:** Use entity search results to surface chunks that pure semantic search might have ranked low. Entities act as an index into chunks via the `entity_sources` join table.

**This is the core "graph as index" step.** It replaces graph traversal (PPR, random walks, etc.) with a simple join: top entities → their source chunks → boost those chunks in the result set.

### Pseudo-algorithm

```python
def boost_chunks_via_entities(
    subquery_results: SubQueryResults,
    top_n_entities: int = 10
) -> SubQueryResults:
    """
    Take top entities from semantic + exact search.
    Find chunks where those entities appear (via entity_sources).
    Add those chunks to the chunk results with a boost.

    This surfaces chunks that:
    - Mention query-relevant entities
    - But might not have scored high on pure semantic similarity
    """

    # Merge entity results: combine semantic + exact match entities
    all_entities = merge_entity_lists(
        subquery_results.semantic_entities,
        subquery_results.exact_entities
    )

    # Take top N entities by score
    top_entities = sorted(all_entities, key=lambda e: e.score, reverse=True)[:top_n_entities]
    top_entity_ids = [e.entity_id for e in top_entities]

    # Find chunks containing these entities
    entity_chunk_rows = db.execute("""
        SELECT
            es.chunk_id,
            COUNT(DISTINCT es.entity_id) as entity_overlap,
            GROUP_CONCAT(e.canonical_name) as matching_entities
        FROM entity_sources es
        JOIN entities e ON e.id = es.entity_id
        WHERE es.entity_id IN ({})
        GROUP BY es.chunk_id
        ORDER BY entity_overlap DESC
    """.format(",".join("?" * len(top_entity_ids))), top_entity_ids)

    # Existing chunk IDs from semantic search
    existing_chunk_ids = {c.chunk_id for c in subquery_results.semantic_chunks}

    boosted_chunks = list(subquery_results.semantic_chunks)  # start with existing

    for row in entity_chunk_rows:
        chunk = get_chunk_by_id(row.chunk_id)

        if row.chunk_id in existing_chunk_ids:
            # Chunk already in results — boost its score
            for c in boosted_chunks:
                if c.chunk_id == row.chunk_id:
                    c.score += ENTITY_OVERLAP_BOOST * row.entity_overlap
                    c.entity_overlap = row.entity_overlap
                    c.matching_entities = row.matching_entities
                    break
        else:
            # New chunk surfaced by entity overlap — add it
            boosted_chunks.append(ScoredChunk(
                chunk_id=row.chunk_id,
                content=chunk.content,
                document_id=chunk.document_id,
                score=ENTITY_OVERLAP_BOOST * row.entity_overlap,
                rank=len(boosted_chunks),
                source="entity_boost",
                entity_overlap=row.entity_overlap,
                matching_entities=row.matching_entities
            ))

    # Re-sort by updated scores
    boosted_chunks.sort(key=lambda c: c.score, reverse=True)

    subquery_results.boosted_chunks = boosted_chunks
    return subquery_results


# Constants
ENTITY_OVERLAP_BOOST = 0.15  # per overlapping entity. Tune empirically.
```

### What This Replaces

This step replaces:
- PPR / Personalized PageRank
- Co-occurrence graph walks
- Community detection
- Path-based traversal

It's doing the same job — using graph structure to improve retrieval — but through a simple join + boost rather than a graph algorithm. The `entity_sources` table IS the graph, used as an index.

### Hub Entity Dampening

High-source-count entities (like "Harper Reed" with 44 sources) would boost too many chunks. Apply a specificity weight:

```python
def entity_specificity_weight(entity: Entity) -> float:
    """
    Dampen the boosting influence of hub entities.
    Entities appearing in many sources get less boost.

    This replaces PPR's natural hub dampening.
    """
    # Threshold scales with corpus size
    threshold = max(5, total_document_count * 0.15)

    if entity.source_count <= threshold:
        return 1.0

    return 1.0 / (1.0 + (entity.source_count - threshold) / threshold)


# Apply when computing boost:
# boost = ENTITY_OVERLAP_BOOST * entity_overlap * avg_specificity_weight
```

### Parameters

| Param | Default | Notes |
|-------|---------|-------|
| `top_n_entities` | 10 | How many seed entities to use for chunk boosting. |
| `ENTITY_OVERLAP_BOOST` | 0.15 | Additive boost per overlapping entity. Tune on real queries. |
| `specificity_threshold_ratio` | 0.15 | Fraction of total docs before dampening kicks in. |

### Latency

- SQLite join query: ~1-5ms
- Total stage: ~5ms

---

## STAGE 3: Cross-Query RRF Fusion + Deduplication

**Purpose:** Merge results from all N sub-queries into a single ranked list. This is where RRF earns its keep — a chunk surfaced by 3 different sub-queries should rank higher than one surfaced by only 1.

### Pseudo-algorithm

```python
def rrf_fuse_across_subqueries(
    all_subquery_results: list[SubQueryResults],
    k: int = 60
) -> FusedResults:
    """
    Apply RRF across all sub-query results.
    Produces one ranked list of entities and one ranked list of chunks.

    RRF formula: score(item) = sum( 1 / (k + rank_i) ) for each list i

    Items appearing in multiple sub-query results get higher scores
    because they accumulate RRF contributions from each appearance.
    """

    # --- Fuse entities ---
    entity_scores = {}  # entity_id -> { rrf_score, entity_data }

    for sq_result in all_subquery_results:
        # Combine semantic + exact entities for this sub-query, deduplicated
        merged_entities = merge_and_rank_entities(
            sq_result.semantic_entities,
            sq_result.exact_entities
        )

        for rank, entity in enumerate(merged_entities):
            eid = entity.entity_id
            rrf_contribution = 1.0 / (k + rank + 1)

            if eid not in entity_scores:
                entity_scores[eid] = {
                    "entity": entity,
                    "rrf_score": 0.0,
                    "appearances": 0,
                    "sub_queries": []
                }

            entity_scores[eid]["rrf_score"] += rrf_contribution
            entity_scores[eid]["appearances"] += 1
            entity_scores[eid]["sub_queries"].append(sq_result.query)

    fused_entities = sorted(
        entity_scores.values(),
        key=lambda x: x["rrf_score"],
        reverse=True
    )

    # --- Fuse chunks ---
    chunk_scores = {}  # chunk_id -> { rrf_score, chunk_data }

    for sq_result in all_subquery_results:
        # Use the boosted chunk list (from Stage 2)
        chunks = sq_result.boosted_chunks

        for rank, chunk in enumerate(chunks):
            cid = chunk.chunk_id
            rrf_contribution = 1.0 / (k + rank + 1)

            if cid not in chunk_scores:
                chunk_scores[cid] = {
                    "chunk": chunk,
                    "rrf_score": 0.0,
                    "appearances": 0,
                    "sub_queries": [],
                    "max_entity_overlap": 0
                }

            chunk_scores[cid]["rrf_score"] += rrf_contribution
            chunk_scores[cid]["appearances"] += 1
            chunk_scores[cid]["sub_queries"].append(sq_result.query)
            chunk_scores[cid]["max_entity_overlap"] = max(
                chunk_scores[cid]["max_entity_overlap"],
                getattr(chunk, 'entity_overlap', 0)
            )

    fused_chunks = sorted(
        chunk_scores.values(),
        key=lambda x: x["rrf_score"],
        reverse=True
    )

    return FusedResults(
        entities=fused_entities,
        chunks=fused_chunks
    )
```

### Why RRF Here Specifically

RRF is not the most sophisticated fusion method. But this is the exact scenario it was designed for: merging ranked lists from independent queries where scores are not comparable. Each sub-query produces its own ranking with its own score semantics (cosine similarity, exact match confidence, entity overlap count). RRF ignores scores entirely and works on rank positions, which makes it robust across these different signals.

**When to upgrade from RRF:** If you accumulate relevance judgments (user clicks, agent feedback on result quality), you can train a learned ranker (LambdaMART, small neural model) using the individual retrieval scores as features. That's strictly better than RRF but requires training data.

### Parameters

| Param | Default | Notes |
|-------|---------|-------|
| `k` | 60 | Standard RRF constant. Lower = top ranks matter more. |
| `max_entities_out` | 20 | Cap entity results after fusion. |
| `max_chunks_out` | 20 | Cap chunk results after fusion. |

---

## STAGE 4: Summarization / Compression

**Purpose:** Compress the fused results into a concise context package for the synthesis LLM. This is NOT a relevance filter — it preserves everything, just makes it shorter.

**When to skip:** If fused results are already within context budget (e.g., ≤15 chunks of reasonable length), pass them directly to Stage 5.

### Pseudo-algorithm

```python
def summarize_results(
    fused: FusedResults,
    original_query: str,
    context_budget_tokens: int = 8000
) -> CompressedContext:
    """
    Compress search results for the synthesis agent.

    Does NOT filter by relevance — that's the synthesis agent's job.
    This step only:
    - Deduplicates overlapping content
    - Extracts key facts from chunks
    - Preserves entity metadata
    - Tracks source references for citation
    """

    # Check if compression is needed
    total_tokens = estimate_tokens(fused)
    if total_tokens <= context_budget_tokens:
        # No compression needed, pass through
        return CompressedContext(
            entities=format_entities(fused.entities),
            chunks=format_chunks(fused.chunks),
            compressed=False
        )

    # Compression needed: summarize chunks
    # Group chunks by document to detect overlap
    chunks_by_doc = group_by(fused.chunks, key=lambda c: c["chunk"].document_id)

    compressed_passages = []

    for doc_id, doc_chunks in chunks_by_doc.items():
        # Sort by position within document
        doc_chunks.sort(key=lambda c: c["chunk"].chunk_id)

        if len(doc_chunks) == 1:
            # Single chunk from this doc, keep as-is but truncate if long
            compressed_passages.append({
                "content": truncate(doc_chunks[0]["chunk"].content, max_tokens=500),
                "document_id": doc_id,
                "rrf_score": doc_chunks[0]["rrf_score"],
                "entity_overlap": doc_chunks[0]["max_entity_overlap"],
                "source": get_document_title(doc_id)
            })
        else:
            # Multiple chunks from same doc — summarize together
            combined_text = "\n".join(c["chunk"].content for c in doc_chunks)
            summary = llm_call(
                f"Summarize the key facts from this text in 2-3 sentences. "
                f"Preserve all named entities and specific claims.\n\n{combined_text}",
                model="haiku"
            )
            compressed_passages.append({
                "content": summary,
                "document_id": doc_id,
                "rrf_score": max(c["rrf_score"] for c in doc_chunks),
                "entity_overlap": max(c["max_entity_overlap"] for c in doc_chunks),
                "source": get_document_title(doc_id)
            })

    return CompressedContext(
        entities=format_entities(fused.entities[:20]),
        passages=compressed_passages,
        compressed=True
    )


def format_entities(fused_entities: list) -> list[dict]:
    """
    Format entities for the synthesis agent.
    Lean representation: name, type, score, why it appeared.
    The agent can request more detail on specific entities if needed.
    """
    return [
        {
            "name": e["entity"].name,
            "type": e["entity"].entity_type,
            "score": round(e["rrf_score"], 4),
            "appeared_in_queries": e["appearances"],
            "description": e["entity"].description[:200] if e["entity"].description else None
        }
        for e in fused_entities
    ]
```

### Parameters

| Param | Default | Notes |
|-------|---------|-------|
| `context_budget_tokens` | 8000 | Total token budget for context passed to synthesis. |
| `max_tokens_per_chunk` | 500 | Truncation limit for individual chunks. |
| `compression_model` | haiku | Cheap model for summarization. |

### Latency

- Without compression: ~0ms (passthrough)
- With compression: ~500ms-1s (one Haiku call per document group)

---

## STAGE 5: Synthesis

**Purpose:** An LLM reads the compressed context and answers the original question. This is the agent's responsibility, not the search system's.

### Interface

The search system returns a `SearchResponse` that the agent consumes:

```python
@dataclass
class SearchResponse:
    """What the search system returns to the agent."""

    # Ranked entities with metadata
    entities: list[dict]
    # [
    #   {
    #     "name": "Harper Reed",
    #     "type": "person",
    #     "score": 0.0318,
    #     "appeared_in_queries": 3,
    #     "description": "Political operative and technologist..."
    #   }
    # ]

    # Ranked passages (chunks, possibly compressed)
    passages: list[dict]
    # [
    #   {
    #     "content": "Harper Reed joined betaworks as...",
    #     "source": "interview-2024-03.md",
    #     "score": 0.0285,
    #     "entity_overlap": 3,
    #     "matching_entities": "Harper Reed, betaworks, seed round"
    #   }
    # ]

    # Metadata
    sub_queries_used: list[str]
    total_entities_considered: int
    total_chunks_considered: int
    compressed: bool
```

### MCP Tool Interface

```python
def search_knowledge_graph(
    query: str,
    top_k: int = 10,
    expand_query: bool = True,
    entity_types: list[str] | None = None
) -> SearchResponse:
    """
    Search the knowledge graph.

    Args:
        query: Natural language search query.
        top_k: Max entities and chunks to return.
        expand_query: If True, run query expansion (adds ~1s latency).
        entity_types: Optional filter. Only return entities of these types.

    Returns:
        SearchResponse with ranked entities and passages.

    Usage by agent:
        The agent can call this multiple times with different queries.
        The agent decides when it has enough context to synthesize.
        The agent handles the final answer generation.
    """

    # Stage 0: Query expansion
    if expand_query:
        sub_queries = expand_query(query)
    else:
        sub_queries = [query]

    # Stage 1+2: Parallel retrieval + entity boost (per sub-query)
    all_results = []
    for sq in sub_queries:
        result = retrieve_for_subquery(sq)
        result = boost_chunks_via_entities(result)
        all_results.append(result)

    # Stage 3: RRF fusion
    fused = rrf_fuse_across_subqueries(all_results)

    # Optional: filter by entity type
    if entity_types:
        fused.entities = [
            e for e in fused.entities
            if e["entity"].entity_type in entity_types
        ]

    # Stage 4: Compression
    compressed = summarize_results(fused, query)

    # Build response
    return SearchResponse(
        entities=compressed.entities[:top_k],
        passages=compressed.passages[:top_k],
        sub_queries_used=sub_queries,
        total_entities_considered=len(fused.entities),
        total_chunks_considered=len(fused.chunks),
        compressed=compressed.compressed
    )
```

---

## Agentic Search Pattern

The search tool above is called by an agent that handles multi-step reasoning. The agent's loop:

```python
def agentic_search(user_question: str) -> str:
    """
    Agent-driven search loop.
    The agent decides when it has enough context.

    This is pseudo-code for the agent's behavior, not a function
    the search system implements.
    """

    context = []
    queries_run = []
    max_rounds = 3

    for round in range(max_rounds):
        if round == 0:
            # First round: search the original question
            result = search_knowledge_graph(user_question, expand_query=True)
        else:
            # Subsequent rounds: agent formulates follow-up queries
            # based on what it learned from previous results
            follow_up = agent_decide_next_query(user_question, context)

            if follow_up is None:
                break  # agent has enough context

            result = search_knowledge_graph(follow_up, expand_query=False)

        context.append(result)
        queries_run.append(result.sub_queries_used)

    # Synthesize final answer from accumulated context
    answer = synthesize(user_question, context)
    return answer
```

### Agent Decisions

The agent makes these decisions (not the search system):

1. **When to stop searching.** If the first round returns high-confidence results with good entity overlap, one round is enough. If results are sparse or tangential, search again.

2. **What to search next.** Based on entities found in round 1, the agent might search for specific entities by name, or search for related concepts that weren't in the original query.

3. **What to include in synthesis.** The agent reads all results and decides what's relevant. The search system does not make relevance judgments.

---

## Graph Neighborhood Expansion (Optional)

**Purpose:** Given a set of seed entities, find connected entities via the relationships table. This is a lightweight alternative to PPR that uses the graph as a join table.

**When to use:** When the agent wants to explore an entity's neighborhood — "who is connected to Harper Reed?" This is NOT part of the default search pipeline. It's an additional tool the agent can invoke.

```python
def get_entity_neighborhood(
    entity_ids: list[int],
    max_neighbors: int = 20
) -> list[dict]:
    """
    Find entities connected to the given seeds via relationships.
    Returns neighbors with relationship metadata.

    Separate MCP tool — not part of the main search pipeline.
    The agent invokes this when it wants to explore connections.
    """

    neighbors = db.execute("""
        SELECT
            CASE
                WHEN r.source_entity_id IN ({seeds}) THEN r.target_entity_id
                ELSE r.source_entity_id
            END as neighbor_id,
            e.canonical_name,
            e.entity_type,
            r.description as relationship_description,
            r.weight,
            e.source_count
        FROM relationships r
        JOIN entities e ON e.id = CASE
            WHEN r.source_entity_id IN ({seeds}) THEN r.target_entity_id
            ELSE r.source_entity_id
        END
        WHERE r.source_entity_id IN ({seeds})
           OR r.target_entity_id IN ({seeds})
        ORDER BY r.weight DESC
        LIMIT ?
    """.format(seeds=",".join("?" * len(entity_ids))),
    [*entity_ids, *entity_ids, max_neighbors])

    # Apply specificity dampening to avoid hub pollution
    results = []
    for row in neighbors:
        weight = row.weight * entity_specificity_weight_from_source_count(row.source_count)
        results.append({
            "entity_id": row.neighbor_id,
            "name": row.canonical_name,
            "type": row.entity_type,
            "relationship": row.relationship_description,
            "weight": weight
        })

    return sorted(results, key=lambda x: x["weight"], reverse=True)
```

---

## Data Structures

```python
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ScoredEntity:
    entity_id: int
    name: str
    entity_type: str
    score: float
    rank: int
    source: str  # "semantic_entity", "exact_match", "entity_boost"
    description: Optional[str] = None
    source_count: Optional[int] = None


@dataclass
class ScoredChunk:
    chunk_id: int
    content: str
    document_id: int
    score: float
    rank: int
    source: str  # "semantic_chunk", "entity_boost"
    entity_overlap: int = 0
    matching_entities: Optional[str] = None


@dataclass
class SubQueryResults:
    query: str
    semantic_entities: list[ScoredEntity] = field(default_factory=list)
    semantic_chunks: list[ScoredChunk] = field(default_factory=list)
    exact_entities: list[ScoredEntity] = field(default_factory=list)
    boosted_chunks: list[ScoredChunk] = field(default_factory=list)


@dataclass
class FusedResults:
    entities: list[dict]  # entity_id -> { entity, rrf_score, appearances }
    chunks: list[dict]    # chunk_id -> { chunk, rrf_score, appearances }


@dataclass
class CompressedContext:
    entities: list[dict]
    passages: list[dict]
    compressed: bool


@dataclass
class SearchResponse:
    entities: list[dict]
    passages: list[dict]
    sub_queries_used: list[str]
    total_entities_considered: int
    total_chunks_considered: int
    compressed: bool
```

---

## Configuration

All tunable parameters in one place:

```python
@dataclass
class SearchConfig:
    # Stage 0: Query expansion
    expansion_enabled: bool = True
    expansion_model: str = "haiku"
    expansion_max_sub_queries: int = 5
    expansion_temperature: float = 0.7

    # Stage 1: Retrieval
    entity_top_k: int = 20
    chunk_top_k: int = 20
    exact_match_min_term_length: int = 3
    exact_match_score: float = 1.0
    partial_match_score: float = 0.7
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dim: int = 384

    # Stage 2: Entity boost
    entity_boost_top_n: int = 10
    entity_overlap_boost: float = 0.15
    specificity_threshold_ratio: float = 0.15

    # Stage 3: RRF fusion
    rrf_k: int = 60
    max_entities_after_fusion: int = 20
    max_chunks_after_fusion: int = 20

    # Stage 4: Compression
    context_budget_tokens: int = 8000
    max_tokens_per_chunk: int = 500
    compression_model: str = "haiku"

    # Stage 5: Synthesis
    synthesis_model: str = "sonnet"  # or whatever the agent uses

    # Agent loop
    max_search_rounds: int = 3
```

---

## Scaling Notes

These are documented here so the implementation doesn't hardcode assumptions that break at scale.

**Current scale:** 263 entities, 54 chunks, 24 documents.
**Target scale:** This framework should work up to ~100K entities and ~50K chunks without architectural changes.

### What changes at scale

| Threshold | Change Needed |
|-----------|--------------|
| ~5K entities | Consider per-type FAISS indexes for precision. Single index starts getting noisy. |
| ~10K entities | Migrate exact match from LIKE to FTS5/BM25. LIKE becomes slow. |
| ~50K chunks | Consider HNSW index instead of flat FAISS. Flat search becomes the bottleneck. |
| ~100K entities | Entity boost query needs indexing on entity_sources. Add composite index on (entity_id, chunk_id). |
| ~100K+ entities | PPR or approximate graph algorithms may start to make sense. NetworkX will be slow. Consider graph database (Neo4j) or approximate PPR libraries. |

### What doesn't change at scale

- The pipeline stages remain the same.
- RRF fusion logic is scale-independent.
- The agentic loop pattern works at any scale.
- Entity specificity dampening works at any scale (threshold scales with corpus size).
- The MCP tool interface remains the same — scale is hidden from the agent.

---

## Testing Strategy

### Unit Tests

```
test_exact_match_finds_entity_by_name()
    → Search "betaworks" returns entity "betaworks" at rank 1

test_semantic_search_finds_related_entities()
    → Search "fundraising" returns funding-related entities

test_entity_boost_surfaces_relevant_chunks()
    → Chunks containing top entities rank higher than chunks without

test_rrf_fusion_rewards_multi_query_hits()
    → Entity appearing in 3 sub-query results ranks above entity in 1

test_hub_dampening_penalizes_high_source_count()
    → "Harper Reed" (44 sources) gets lower boost than specific entities

test_specificity_threshold_scales_with_corpus()
    → Threshold adjusts as total_document_count changes
```

### Integration Tests

```
test_full_pipeline_returns_relevant_results()
    → End-to-end: query → expansion → retrieval → fusion → response

test_query_expansion_produces_useful_sub_queries()
    → Sub-queries are semantically related to original query
    → Sub-queries are distinct from each other (not duplicative)

test_no_expansion_mode_works()
    → expand_query=False skips Stage 0, uses single query

test_entity_type_filter_works()
    → entity_types=["person"] only returns person entities

test_agentic_multi_round_improves_results()
    → Agent's second search finds entities missed in first round
```

### Quality Benchmarks

Build a small evaluation set of (query, expected_entities, expected_chunks) triples:

```python
eval_set = [
    {
        "query": "Harper Reed fundraising",
        "expected_entities": ["Harper Reed", "betaworks", ...],
        "expected_chunks": [chunk_ids_that_discuss_fundraising],
    },
    {
        "query": "betaworks",
        "expected_entities": ["betaworks"],  # exact match must work
        "expected_chunks": [...],
    },
    # ... 20-50 examples covering different query types
]

# Metrics:
# - Recall@10: What fraction of expected entities appear in top 10?
# - MRR: What's the average rank of the first expected entity?
# - Entity overlap precision: Do boosted chunks actually contain relevant entities?
```

---

## File Structure (Suggested)

```
orchestrator/src/pipeline/
├── search/
│   ├── __init__.py
│   ├── config.py              # SearchConfig dataclass
│   ├── models.py              # ScoredEntity, ScoredChunk, etc.
│   ├── pipeline.py            # Main search_knowledge_graph() entry point
│   ├── expansion.py           # Stage 0: query expansion
│   ├── retrieval.py           # Stage 1: FAISS + exact match
│   ├── entity_boost.py        # Stage 2: entity-based chunk boosting
│   ├── fusion.py              # Stage 3: RRF fusion
│   ├── compression.py         # Stage 4: summarization
│   ├── neighborhood.py        # Optional: graph neighborhood expansion
│   └── tests/
│       ├── test_retrieval.py
│       ├── test_fusion.py
│       ├── test_entity_boost.py
│       └── test_integration.py
```

---

## What This Spec Intentionally Omits

1. **Graph traversal algorithms (PPR, random walks, community detection).** The graph is used as a join table, not a query engine. If needed later, add as a separate tool the agent can invoke.

2. **Per-type FAISS indexes.** Not worth the complexity until ~5K+ entities. Add when the single index gets noisy.

3. **Cross-encoder reranking.** The LLM reranking via the agent loop handles this. Add a dedicated cross-encoder if latency budget is too tight for LLM calls.

4. **Knowledge graph embeddings (TransE, RotatE).** These matter for entity resolution and relationship prediction, not for retrieval. Add to the extraction pipeline, not the search pipeline.

5. **Edge type ontology.** Edges are lightweight with free-text descriptions. Edge clustering/typing is an extraction concern, not a search concern. Search treats edge descriptions as searchable text metadata.
