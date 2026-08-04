# ABOUTME: Main search pipeline — 5 stages (expansion → retrieval → entity-boost → fusion → response).
# ABOUTME: Accepts an optional Relay instance for LLM-powered query expansion.

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orrery_relay import Relay

from .config import SearchConfig
from .models import SubQueryResults, ScoredEntity, ScoredChunk, SearchResponse
from .retrieval import (
    build_indexes, embed_text, embed_new_entities, embed_new_chunks,
    search_entities_semantic, search_chunks_semantic, search_entities_exact,
)
from .entity_boost import boost_chunks_via_entities
from .fusion import rrf_fuse

_config = SearchConfig()
_indexes_ready = False


def _enrich_results(conn: sqlite3.Connection, results: SubQueryResults):
    """Fill in entity names/types and chunk text from DB."""
    for e in results.semantic_entities:
        row = conn.execute("SELECT canonical_name, type FROM entities WHERE id = ?", (e.entity_id,)).fetchone()
        if row:
            e.name = row[0]
            e.entity_type = row[1]
            e.source_count = conn.execute(
                "SELECT COUNT(*) FROM entity_sources WHERE entity_id = ?", (e.entity_id,)
            ).fetchone()[0]

    for c in results.semantic_chunks:
        row = conn.execute(
            "SELECT c.text, c.document_id, d.title FROM chunks c JOIN documents d ON c.document_id = d.id WHERE c.id = ?",
            (c.chunk_id,)
        ).fetchone()
        if row:
            c.text = row[0][:300]
            c.document_id = row[1]
            c.document_title = row[2] or ""


def _retrieve_for_subquery(conn: sqlite3.Connection, query: str) -> SubQueryResults:
    """Stage 1: Run all retrieval channels for a single sub-query."""
    query_embedding = embed_text(query)

    # Channel A: Semantic entity search
    semantic_entities = search_entities_semantic(query_embedding, top_k=_config.entity_top_k)

    # Channel B: Semantic chunk search
    semantic_chunks = search_chunks_semantic(query_embedding, top_k=_config.chunk_top_k)

    # Channel C: Exact match
    exact_entities = search_entities_exact(conn, query, min_term_length=_config.exact_min_term_length)

    results = SubQueryResults(
        query=query,
        semantic_entities=semantic_entities,
        semantic_chunks=semantic_chunks,
        exact_entities=exact_entities,
    )

    # Enrich with names/text from DB
    _enrich_results(conn, results)

    return results


async def search_knowledge_graph(
    conn: sqlite3.Connection,
    query: str,
    expand: bool = False,
    relay: "Relay | None" = None,
    top_k: int = 20,
) -> SearchResponse:
    """Full search pipeline. Returns ranked entities + chunks."""
    global _indexes_ready

    _config.max_results = top_k

    # Ensure indexes are built
    if not _indexes_ready:
        build_indexes(conn)
        _indexes_ready = True

    # Stage 0: Query expansion
    if expand and relay is not None:
        from .expansion import expand_query
        sub_queries = await expand_query(
            relay=relay,
            query=query,
            max_sub_queries=_config.expansion_max_sub_queries,
        )
    else:
        sub_queries = [query]

    # Get total doc count for specificity
    total_docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]

    # Stage 1 + 2: Retrieve + entity-boost for each sub-query
    all_results = []
    for sq in sub_queries:
        result = _retrieve_for_subquery(conn, sq)
        result = boost_chunks_via_entities(conn, result, _config, total_docs)
        all_results.append(result)

    # Stage 3: RRF fusion
    response = rrf_fuse(all_results, query, _config)

    return response


# Re-export for backward compat
__all__ = ["search_knowledge_graph", "build_indexes", "embed_new_entities", "embed_new_chunks"]
