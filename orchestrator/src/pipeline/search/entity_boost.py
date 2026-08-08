"""Stage 2: Entity-based chunk boosting — use entities as an index into chunks."""

import sqlite3
from .models import SubQueryResults, ScoredChunk
from .config import SearchConfig


def entity_specificity_weight(source_count: int, total_docs: int) -> float:
    """Dampen hub entities. Entities appearing in many docs get less boost."""
    threshold = max(5, total_docs * 0.15)
    if source_count <= threshold:
        return 1.0
    return 1.0 / (1.0 + (source_count - threshold) / threshold)


def boost_chunks_via_entities(
    conn: sqlite3.Connection,
    results: SubQueryResults,
    config: SearchConfig,
    total_docs: int,
) -> SubQueryResults:
    """Take top entities, find their chunks, boost those chunks."""

    # Merge semantic + exact entities, sorted by score
    all_entities = sorted(
        results.semantic_entities + results.exact_entities,
        key=lambda e: e.score, reverse=True
    )

    # Deduplicate
    seen = set()
    unique = []
    for e in all_entities:
        if e.entity_id not in seen:
            seen.add(e.entity_id)
            unique.append(e)
    top_entities = unique[:config.entity_boost_top_n]

    if not top_entities:
        results.boosted_chunks = list(results.semantic_chunks)
        return results

    top_ids = [e.entity_id for e in top_entities]
    placeholders = ",".join("?" * len(top_ids))

    # Find chunks containing these entities
    rows = conn.execute(f"""
        SELECT es.chunk_id, COUNT(DISTINCT es.entity_id) as overlap,
               GROUP_CONCAT(e.canonical_name, ', ') as names
        FROM entity_sources es
        JOIN entities e ON e.id = es.entity_id AND e.invalid_at IS NULL
        WHERE es.entity_id IN ({placeholders}) AND es.chunk_id IS NOT NULL
        GROUP BY es.chunk_id
        ORDER BY overlap DESC
    """, top_ids).fetchall()

    # Get specificity weights for top entities
    specificity = {}
    for e in top_entities:
        specificity[e.entity_id] = entity_specificity_weight(e.source_count, total_docs)
    avg_specificity = sum(specificity.values()) / max(len(specificity), 1)

    # Build boosted chunk list
    existing_ids = {c.chunk_id for c in results.semantic_chunks}
    boosted = list(results.semantic_chunks)

    for row in rows:
        chunk_id, overlap, matching_names = row[0], row[1], row[2] or ""
        boost = config.entity_overlap_boost * overlap * avg_specificity

        if chunk_id in existing_ids:
            # Boost existing chunk
            for c in boosted:
                if c.chunk_id == chunk_id:
                    c.score += boost
                    c.entity_overlap = overlap
                    c.matching_entities = matching_names
                    break
        else:
            # Add new chunk surfaced by entity overlap
            chunk = conn.execute(
                "SELECT c.id, c.text, c.document_id, d.title FROM chunks c JOIN documents d ON c.document_id = d.id WHERE c.id = ?",
                (chunk_id,)
            ).fetchone()
            if chunk:
                boosted.append(ScoredChunk(
                    chunk_id=chunk[0], text=chunk[1][:300],
                    document_id=chunk[2], document_title=chunk[3] or "",
                    score=boost, rank=len(boosted),
                    source="entity_boost",
                    entity_overlap=overlap, matching_entities=matching_names,
                ))

    boosted.sort(key=lambda c: c.score, reverse=True)
    results.boosted_chunks = boosted
    return results
