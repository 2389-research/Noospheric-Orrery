# Search System

Hybrid semantic search over the Noospheric Orrery knowledge graph. Entities are the primary search surface. Chunks are evidence. The graph structure (entity → chunk relationships) is used as an index, not a traversal engine.

## Pipeline

```
User/Agent: "fundraising strategy"
    │
    ▼
Stage 0: Query Expansion (Haiku, ~1s)
    → "fundraising strategy"
    → "fundraising techniques and methods"
    → "capital raising and funding acquisition strategies"
    → "nonprofit donation strategies"
    → "how to develop a fundraising plan"
    │
    ▼
For each sub-query (parallel):
    │
    ├── Stage 1a: FAISS Entity Search
    │   Embed query → cosine similarity against entity name embeddings
    │   → finds semantically similar entities
    │
    ├── Stage 1b: FAISS Chunk Search
    │   Embed query → cosine similarity against document chunk embeddings
    │   → finds relevant document passages
    │
    ├── Stage 1c: Exact Match
    │   SQL LIKE on entity canonical names
    │   → catches exact names FAISS might miss ("betaworks" → "betaworks")
    │
    ▼
Stage 2: Entity-Based Chunk Boosting (per sub-query)
    Take top entities from 1a+1c → look up their source chunks via entity_sources
    → chunks containing query-relevant entities get score boost
    → hub entities dampened by specificity weight
    This is the "graph as index" step — entities point to chunks
    │
    ▼
Stage 3: RRF Fusion (across all sub-queries)
    Merge ranked lists from all 5 sub-queries
    → entity found by 4/5 sub-queries ranks above entity found by 1/5
    → RRF ignores raw scores, works on rank positions only
    │
    ▼
Return: ranked entities + ranked chunks + sub-queries used
    The search system does NOT synthesize answers
    The calling agent/UI decides what to do with results
```

## How Each Stage Works

### Stage 0: Query Expansion

One Haiku call expands a single query into 3-5 sub-queries covering synonyms, related concepts, and more specific phrasings. This is the highest-leverage step — "fundraising" alone misses "capital raising", "seed round", "series A", etc.

- Model: Haiku (via Bedrock)
- Latency: ~500ms-1s
- Cost: ~$0.0005
- Can be skipped with `expand=false` for exact lookups

### Stage 1: Parallel Retrieval

Three channels run concurrently for each sub-query:

**Channel A: Semantic Entity Search (FAISS)**
- all-MiniLM-L6-v2 embeddings, 384-dim, stored in DB
- FAISS IndexFlatIP (inner product on normalized vectors = cosine similarity)
- Returns top-K entities ranked by embedding similarity to query

**Channel B: Semantic Chunk Search (FAISS)**
- Same model and index type, over document chunk text
- Chunks truncated to 512 chars for embedding
- Returns top-K chunks ranked by similarity

**Channel C: Exact Match (SQLite LIKE)**
- Full name match (score 1.0) + substring match per term (score 0.7)
- Catches entities that embed poorly but match exactly
- Terms < 3 chars skipped to avoid noise
- At scale (>10K entities) migrate to FTS5/BM25

### Stage 2: Entity-Based Chunk Boosting

The key insight: **entities are an index into chunks**. This replaces graph traversal (PPR, random walks) with a simple join.

1. Take top 10 entities from Channels A+C
2. Query `entity_sources` to find chunks containing those entities
3. Boost those chunks' scores by `overlap_count × specificity_weight`
4. Chunks that contain multiple query-relevant entities rank highest

**Hub dampening:** Entities appearing in many documents get reduced boost:
```python
specificity = 1 / (1 + max(0, source_count - threshold) / threshold)
# threshold = max(5, total_docs × 0.15)
```

This prevents "harper reed" (44 sources) from boosting every chunk in the corpus.

### Stage 3: RRF Fusion

Reciprocal Rank Fusion merges results across all sub-queries:
```
score(entity) = Σ 1/(K + rank_i)  for each sub-query i that found it
```

An entity found by multiple sub-queries accumulates score from each appearance. K=60 (standard RRF constant). This works because RRF is rank-based, not score-based — different channels produce incomparable scores.

## Embedding Storage

Embeddings are stored as BLOB columns on `entities` and `chunks` tables. This means:
- FAISS indexes rebuild instantly from stored embeddings on startup
- New entities/chunks get embedded after extraction (via `embed_new_entities()`)
- No re-embedding on restart — only new items need embedding

Model: `all-MiniLM-L6-v2` (384-dim, sentence-transformers)

## API

```
GET /search?q=fundraising+strategy&top_k=20&expand=true
→ {
    query: "fundraising strategy",
    sub_queries_used: ["fundraising strategy", "capital raising...", ...],
    entities: [{id, name, type, score, source_count, appearances, paths}, ...],
    chunks: [{chunk_id, text, document_id, document_title, score, entity_overlap}, ...],
    total_entities: 44,
    total_chunks: 38
  }

POST /search/rebuild
→ Embeds unembedded entities/chunks, rebuilds FAISS indexes
→ {status, new_entities_embedded, new_chunks_embedded, entities, chunks}
```

## Galaxy Viz Integration

Search results trigger the bioluminescence glow effect in the galaxy visualization:
1. Search completes → top entity names broadcast via WebSocket
2. Viz page receives → forwards to iframe via postMessage
3. Galaxy entities flash → domains swell → routes pulse
4. Glow propagates in search ranking order (top result first)

Any search source triggers the glow — UI search bar, API calls, MCP tool calls from agents.

## MCP Tool

The `search_knowledge_graph` MCP tool wraps this pipeline:
```
Agent calls search_knowledge_graph(query="fundraising strategy")
→ orchestrator runs full pipeline
→ broadcasts to viz WebSocket
→ returns formatted text to agent
```

The agent decides whether to search again based on results. The search system doesn't make relevance judgments.

## File Structure

```
orchestrator/src/pipeline/search/
├── __init__.py          # Exports
├── config.py            # SearchConfig dataclass
├── models.py            # ScoredEntity, ScoredChunk, SubQueryResults, SearchResponse
├── expansion.py         # Stage 0: Haiku query expansion
├── retrieval.py         # Stage 1: FAISS + exact match + embedding management
├── entity_boost.py      # Stage 2: Entity-based chunk boosting + hub dampening
├── fusion.py            # Stage 3: RRF fusion across sub-queries
└── pipeline.py          # Main entry point wiring stages together
```

## Current Scale

- 263 entities, 54 chunks, 24 documents
- FAISS flat index (exact search) — fast at this scale
- At ~5K entities: consider per-type FAISS indexes
- At ~50K chunks: consider HNSW approximate index
- At ~10K entities: migrate exact match to FTS5/BM25

## What This Intentionally Omits

- **Graph traversal algorithms (PPR, random walks)** — entity_sources join replaces this
- **Cross-encoder reranking** — the agent loop handles multi-step refinement
- **Answer synthesis** — the downstream LLM does this, not the search system
- **Result compression** — deferred until corpus exceeds context budget (~8K tokens)
- **Per-type FAISS indexes** — not worth it until ~5K entities
