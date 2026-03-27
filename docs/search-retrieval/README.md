# Search & Retrieval System

Hybrid search over 659+ enriched tutorial transcripts. Returns ranked entities, transcript chunks with timestamped YouTube deep links, co-occurrence graph context, and relevant videos.

## Architecture

Four parallel retrieval paths fused with Reciprocal Rank Fusion (RRF):

```
User Query
    │
    ├── FAISS (per-type)      19 entity type indexes, cosine similarity
    ├── BM25 (SQLite FTS5)    Keyword search on full transcripts, TF-IDF weighted
    ├── Graph expansion       NetworkX co-occurrence, seed from top entities
    └── Chunk retrieval       11,320 transcript chunks with timestamps
    │
    ▼
RRF Fusion → Ranked entities + transcript excerpts + videos + graph context
```

## Indexes

| Component | Contents | Size |
|-----------|----------|------|
| SQLite (`search_db.sqlite`) | 681 videos, 40,617 entity mentions, 13,567 unique entities, FTS5, 11,320 chunks | 31MB |
| Per-type FAISS (`search_indexes/`) | 19 indexes, all-MiniLM-L6-v2, 384-dim | 20MB |
| Chunk FAISS | 11,320 transcript chunks embedded | 17MB |
| NetworkX graph (`graph.gml`) | 12,159 nodes, 1.3M co-occurrence edges | 80MB |

## Usage

```python
from search.search import SearchEngine

engine = SearchEngine()
results = engine.search("how to paint NMM gold", top_k=10)

results.entities       # Ranked entities with corpus stats
results.chunks         # Transcript excerpts with .text, .url, .timestamp
results.videos         # Videos ranked by entity overlap
results.graph_context  # Co-occurring entities from graph traversal
```

## Key Design Decisions

- **Per-type FAISS indexes** — one IndexFlatIP per entity type. True pre-filtering, not post-filtering.
- **BM25 with TF-IDF weighting** — penalizes globally common entities ("airbrush" in 304 videos gets low IDF).
- **Graph source selection** — avoids ultra-common hub entities as graph expansion sources. Uses specificity penalty.
- **Chunks carry timestamps** — each chunk has start_time/end_time for YouTube deep links (`youtu.be/{id}?t={seconds}`).

## Known Gaps

- **Abbreviations don't match full names** — "NMM" doesn't embed near "non-metallic metal". Solved by query expansion.
- **Recipe steps don't match recipe queries** — instructional text embeds differently from query text. Cross-encoder reranker would help.
- **Fragmented product names** — "agrax" vs "agrax earth shade" from transcript garbling.

## Source Data

Built from:
```
miner_output/
  transcripts/{video_id}.json              # 507 transcript files
  metadata/{video_id}.json                 # 529 video metadata files
  local_enrichment_final/{video_id}.json   # 659 enrichment files
  normalization/                           # clusters, normalization_map
```

## Location

- **Code:** `DS-scratch/warhammer_mini_sizes/search/search.py`
- **Builder:** `DS-scratch/warhammer_mini_sizes/search/build_index.py`
- **CLI:** `DS-scratch/warhammer_mini_sizes/search/query.py`
- **Guide:** `DS-scratch/warhammer_mini_sizes/docs/search-system-guide.md`
- **Deployed artifacts:** `tutorial-rag/data/` on spark
