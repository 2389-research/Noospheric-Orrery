# Search Improvement — Research Brief

**Date:** 2026-03-28
**Status:** Needs research
**Purpose:** Spec out what a production-quality search should look like for the Noospheric Orrery knowledge graph

## What Exists Today

A 3-path hybrid search with RRF fusion:

```
GET /search?q=fundraising strategy

Path 1: FAISS entity search (all-MiniLM-L6-v2, 384-dim)
  → Embeds query, finds semantically similar entity names
  → Returns: entities ranked by cosine similarity

Path 2: FAISS chunk search (same model)
  → Embeds query, finds semantically similar document chunks
  → Returns: document excerpts ranked by cosine similarity

Path 3: Co-occurrence graph expansion
  → Takes top 5 entities from Path 1 as seeds
  → Walks co-occurrence edges (from relationships table)
  → Returns: entities connected to the seed entities

Fusion: Reciprocal Rank Fusion (RRF) merges entity results from paths 1+3
Chunks returned separately (not fused with entities)
```

Code: `orchestrator/src/pipeline/search.py`

## Current Data Scale

- 263 entities across ~10 types
- 54 document chunks (24 documents)
- Co-occurrence edges in relationships table
- All entities and chunks embedded with all-MiniLM-L6-v2

## Known Issues

### 1. Hub entity dominance
Entities like "Harper Reed" (44 sources) appear in every search result because:
- They embed near many queries (high semantic similarity to common terms)
- They dominate the co-occurrence graph (connected to everything)
- RRF doesn't penalize frequency — a high-ranked result is high-ranked regardless of how common it is

The warhammer system solved this with a specificity penalty:
```python
specificity = 1 / (1 + max(0, source_count - threshold) / threshold)
```

### 2. No query expansion
A single query misses synonyms, abbreviations, and related concepts. The warhammer RAG pipeline uses query expansion (one LLM call) to turn "fundraising" into:
- "fundraising rounds seed series A"
- "investor meetings pitch deck"
- "venture capital VC funding"
- "raising money startup"

Each sub-query is searched independently, results merged. This dramatically improves recall.

### 3. Entity → chunk relationship is underused
We search entities and chunks independently. But entities know which chunks they came from (entity_sources table has chunk_id). A better flow:
1. Find relevant entities
2. Find the chunks where those entities appear together
3. Rank chunks by how many query-relevant entities they contain

This is "entity-first retrieval with chunk subsetting" — entities are the index, chunks are the content.

### 4. No keyword/exact match path
FAISS embedding search is great for semantic similarity but misses exact name matches. "Betaworks" as a query should find the entity "betaworks" with perfect confidence, but embedding search might rank other things higher. BM25/FTS5 would catch this.

**Open question:** Is BM25 worth adding for a corpus this size? At 263 entities and 54 chunks, exact string matching (LIKE queries) might be sufficient and simpler than maintaining FTS5 indexes.

## What the Warhammer System Does

Reference: `docs/search-retrieval/README.md` and the deployed system at `DS-scratch/warhammer_mini_sizes/search/`

### 4-path hybrid:

**Path 1: FAISS per-type indexes**
- 19 separate FAISS indexes (one per entity type)
- Query is searched against type-specific indexes
- True pre-filtering — searching "technique" entities doesn't waste comparisons on "person" entities
- Each index uses all-MiniLM-L6-v2, 384-dim

**Path 2: BM25 + TF-IDF (SQLite FTS5)**
- Full-text search on entity names and descriptions
- TF-IDF weighting penalizes globally common entities
- Formula: `(hit_count / n_videos) × log(total / global_count)`
- Catches exact name matches that embedding search misses

**Path 3: Graph expansion with specificity penalty**
- NetworkX co-occurrence graph (12,159 nodes, 1.3M edges)
- Seed from top entity hits
- Expand to neighbors via co-occurrence edges
- Specificity penalty for hub entities: `1 / (1 + max(0, video_count - 100) / 100)`
- Prevents "airbrush" (appears in 304 videos) from dominating every result

**Path 4: Chunk retrieval**
- 11,320 transcript chunks embedded with all-MiniLM-L6-v2
- Separate FAISS index for chunks
- Each chunk carries source document + timestamp
- Enables deep links to specific moments in videos

**Fusion: RRF across all 4 paths**

### The RAG layer on top:

The tutorial RAG pipeline (`docs/tutorial-rag/README.md`) adds:
1. **Query expansion** — LLM generates 5-7 sub-queries
2. **Parallel retrieval** — each sub-query hits the search engine
3. **Synthesis** — LLM generates a structured answer from retrieved chunks
4. **Judge** — LLM evaluates answer quality against evidence
5. **Verify-fix loop** — up to 2 iterations to improve the answer

## Questions for the Research Agent

### Architecture questions:
1. **Should we do per-type FAISS indexes?** At 263 entities it's overkill, but at 10K+ it matters. What's the threshold where per-type indexing becomes worth the complexity?

2. **BM25 vs exact match:** For our corpus size, would simple `WHERE canonical_name LIKE '%query%'` on SQLite perform comparably to FTS5/BM25? What's the quality/complexity tradeoff?

3. **Entity-first vs chunk-first retrieval:** The warhammer system searches entities first and uses them to find relevant chunks. Is this always better, or are there query types where chunk-first (our current approach) returns better results?

### Quality questions:
4. **Query expansion cost:** One LLM call per search adds ~1-2s latency and ~$0.001 cost. Is it worth it at our scale? The warhammer system says it's "mandatory" — is that true for all corpus types or specific to domain-specific jargon?

5. **Specificity penalty tuning:** The warhammer formula uses `threshold=100`. Our corpus is 24 docs. What should the threshold be? How does it scale with corpus size?

6. **Cross-encoder reranking:** The warhammer system notes this as a gap. Is it worth adding a cross-encoder reranker after the initial retrieval pass? What's the latency/quality tradeoff?

### Integration questions:
7. **Search + galaxy glow:** Right now we fire the glow after search returns. Should the glow also fire during retrieval to show the search "exploring" the graph? i.e., as each sub-query hits, its entities glow, creating a wave of exploration before the final results are shown.

8. **MCP tool design:** The current `search_knowledge_graph` tool returns flat text. Should it return structured data (entities + chunks + scores) so the agent can reason about which results to pursue? What's the right level of abstraction for an agent tool?

9. **Search result caching:** Should we cache search results? The FAISS search is fast (~50ms) but query expansion adds LLM latency. Cache the expansion? Cache the full result?

## What We Think the Right Architecture Is

```
User/Agent query
    │
    ├── Query expansion (Haiku, ~1s) — if enabled
    │   → 5-7 sub-queries
    │
    ├── For each (sub-)query:
    │   ├── FAISS entity search (with specificity penalty)
    │   ├── FAISS chunk search
    │   ├── Optional: exact match on entity names
    │   └── Graph expansion from top entity hits
    │
    ├── RRF fusion across all paths and sub-queries
    │
    ├── Entity-first chunk subsetting:
    │   → Find chunks where top entities co-appear
    │   → Rank by entity overlap density
    │
    └── Return: ranked entities + ranked chunks + graph context
```

But we want the research agent to validate or challenge this before we build it. Specifically:
- Is there a simpler architecture that works just as well at our scale?
- Are there recent (2025-2026) techniques that supersede the 4-path hybrid?
- How does this compare to vector DB approaches (Pinecone, Weaviate) that handle hybrid search natively?

## Constraints

- Must run locally (no external services beyond Bedrock for LLM calls)
- Must be fast enough for interactive use (<3s for search)
- Must work with SQLite (no Postgres requirement)
- Must produce entity names for the galaxy glow effect
- Must be queryable via MCP tools by AI agents
- FAISS is already installed and working
