"""Stage 3: Cross-query RRF fusion + deduplication."""

from collections import defaultdict
from .models import SubQueryResults, SearchResponse
from .config import SearchConfig


def rrf_fuse(
    all_results: list[SubQueryResults],
    original_query: str,
    config: SearchConfig,
) -> SearchResponse:
    """Merge results from all sub-queries via RRF."""
    K = config.rrf_k

    # Fuse entities
    entity_scores: dict[str, dict] = {}
    for sq in all_results:
        merged = sorted(
            sq.semantic_entities + sq.exact_entities,
            key=lambda e: e.score, reverse=True
        )
        seen = set()
        for rank, e in enumerate(merged):
            if e.entity_id in seen:
                continue
            seen.add(e.entity_id)
            rrf = 1.0 / (K + rank + 1)
            if e.entity_id not in entity_scores:
                entity_scores[e.entity_id] = {
                    "id": e.entity_id, "name": e.name, "type": e.entity_type,
                    "source_count": e.source_count, "rrf_score": 0.0,
                    "appearances": 0, "sub_queries": [], "paths": set(),
                }
            entity_scores[e.entity_id]["rrf_score"] += rrf
            entity_scores[e.entity_id]["appearances"] += 1
            entity_scores[e.entity_id]["sub_queries"].append(sq.query)
            entity_scores[e.entity_id]["paths"].add(e.source)
            # Keep best name/type
            if not entity_scores[e.entity_id]["name"]:
                entity_scores[e.entity_id]["name"] = e.name
                entity_scores[e.entity_id]["type"] = e.entity_type

    fused_entities = sorted(entity_scores.values(), key=lambda x: -x["rrf_score"])
    for e in fused_entities:
        e["paths"] = list(e["paths"])
        e["score"] = round(e["rrf_score"], 4)

    # Fuse chunks
    chunk_scores: dict[str, dict] = {}
    for sq in all_results:
        chunks = sq.boosted_chunks if sq.boosted_chunks else sq.semantic_chunks
        for rank, c in enumerate(chunks):
            rrf = 1.0 / (K + rank + 1)
            if c.chunk_id not in chunk_scores:
                chunk_scores[c.chunk_id] = {
                    "chunk_id": c.chunk_id, "text": c.text,
                    "document_id": c.document_id, "document_title": c.document_title,
                    "rrf_score": 0.0, "appearances": 0,
                    "entity_overlap": 0, "matching_entities": "",
                }
            chunk_scores[c.chunk_id]["rrf_score"] += rrf
            chunk_scores[c.chunk_id]["appearances"] += 1
            chunk_scores[c.chunk_id]["entity_overlap"] = max(
                chunk_scores[c.chunk_id]["entity_overlap"], c.entity_overlap
            )
            if c.matching_entities:
                chunk_scores[c.chunk_id]["matching_entities"] = c.matching_entities

    fused_chunks = sorted(chunk_scores.values(), key=lambda x: -x["rrf_score"])
    for c in fused_chunks:
        c["score"] = round(c["rrf_score"], 4)

    sub_queries = [sq.query for sq in all_results]

    return SearchResponse(
        query=original_query,
        entities=fused_entities[:config.max_results],
        chunks=fused_chunks[:config.max_results],
        sub_queries_used=sub_queries,
        total_entities=len(fused_entities),
        total_chunks=len(fused_chunks),
    )
