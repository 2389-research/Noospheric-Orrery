from fastapi import APIRouter, HTTPException
from ..config import get_settings
from ..db import get_connection

router = APIRouter()

@router.get("/entities")
def list_entities(
    limit: int = 50,
    offset: int = 0,
    type: str | None = None,
    domain: str | None = None,
    job_id: str | None = None,
):
    settings = get_settings()
    conn = get_connection(settings.db_path)

    if job_id:
        # Job-scoped query: entities extracted by this specific job
        # Also compute is_new: entity was created during this job
        job = conn.execute(
            "SELECT started_at, completed_at FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()

        query = """
            SELECT DISTINCT e.id, e.canonical_name, e.type,
                   (SELECT COUNT(*) FROM entity_sources es2 WHERE es2.entity_id = e.id) as source_count,
                   CASE WHEN e.created_at >= ? AND e.created_at <= ? THEN 1 ELSE 0 END as is_new
            FROM entities e
            JOIN entity_sources es ON e.id = es.entity_id AND es.job_id = ?
        """
        params: list = [
            job["started_at"] if job else "1970-01-01",
            job["completed_at"] if job else "2099-01-01",
            job_id,
        ]

        conditions = []
        if type:
            conditions.append("e.type = ?")
            params.append(type)
        if domain:
            query += " JOIN document_domains dd ON es.document_id = dd.document_id AND dd.domain_path LIKE ? || '%'"
            params.append(domain)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY is_new DESC, source_count DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [
            {"id": r[0], "canonical_name": r[1], "type": r[2], "source_count": r[3], "is_new": bool(r[4])}
            for r in rows
        ]
    else:
        # Default query: all entities
        query = "SELECT e.id, e.canonical_name, e.type, (SELECT COUNT(*) FROM entity_sources es WHERE es.entity_id = e.id) as source_count FROM entities e"
        params = []
        conditions = []
        if domain:
            query += " JOIN entity_sources es2 ON e.id = es2.entity_id JOIN document_domains dd ON es2.document_id = dd.document_id AND dd.domain_path LIKE ? || '%'"
            params.append(domain)
        if type:
            conditions.append("e.type = ?")
            params.append(type)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " GROUP BY e.id ORDER BY source_count DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [{"id": r[0], "canonical_name": r[1], "type": r[2], "source_count": r[3]} for r in rows]


@router.get("/entities/{entity_id}/cooccurrences")
def get_cooccurrences(entity_id: str, limit: int = 10):
    """Get entities that co-occur with this entity (share document chunks)."""
    settings = get_settings()
    conn = get_connection(settings.db_path)
    rows = conn.execute("""
        SELECT e.id, e.canonical_name, e.type, r.weight
        FROM relationships r
        JOIN entities e ON (
            CASE WHEN r.from_entity = ? THEN r.to_entity ELSE r.from_entity END
        ) = e.id
        WHERE (r.from_entity = ? OR r.to_entity = ?) AND r.type = 'co_occurs'
        ORDER BY r.weight DESC
        LIMIT ?
    """, (entity_id, entity_id, entity_id, limit)).fetchall()
    conn.close()
    return [
        {"id": r[0], "canonical_name": r[1], "type": r[2], "weight": r[3]}
        for r in rows
    ]


@router.get("/entities/{entity_id}/star-graph")
def get_star_graph(entity_id: str, co_limit: int = 30):
    """Return the 2-hop graph for the star view: entity → docs → co-entities.

    Returns which documents mention this entity, and for each co-occurring entity,
    which documents they share.
    """
    settings = get_settings()
    conn = get_connection(settings.db_path)

    # Get documents that mention this entity
    doc_rows = conn.execute("""
        SELECT DISTINCT d.id, d.title
        FROM entity_sources es
        JOIN documents d ON es.document_id = d.id
        WHERE es.entity_id = ?
        ORDER BY d.title
    """, (entity_id,)).fetchall()

    doc_ids = [r[0] for r in doc_rows]
    documents = [{"id": r[0], "title": r[1]} for r in doc_rows]

    # Get co-occurring entities (from relationships table), deduped
    co_rows = conn.execute("""
        SELECT e.id, e.canonical_name, e.type, SUM(r.weight) as total_weight
        FROM relationships r
        JOIN entities e ON (
            CASE WHEN r.from_entity = ? THEN r.to_entity ELSE r.from_entity END
        ) = e.id
        WHERE (r.from_entity = ? OR r.to_entity = ?) AND r.type = 'co_occurs'
        GROUP BY e.id
        ORDER BY total_weight DESC
        LIMIT ?
    """, (entity_id, entity_id, entity_id, co_limit)).fetchall()

    co_entity_ids = list(dict.fromkeys(r[0] for r in co_rows))  # dedup preserving order

    # For each co-entity, find which docs they share with the central entity
    shared_docs = {}
    if co_entity_ids and doc_ids:
        placeholders_co = ",".join("?" * len(co_entity_ids))
        placeholders_doc = ",".join("?" * len(doc_ids))
        shared_rows = conn.execute(f"""
            SELECT es.entity_id, es.document_id
            FROM entity_sources es
            WHERE es.entity_id IN ({placeholders_co})
              AND es.document_id IN ({placeholders_doc})
        """, co_entity_ids + doc_ids).fetchall()

        for row in shared_rows:
            eid, did = row[0], row[1]
            shared_docs.setdefault(eid, []).append(did)

    co_entities = []
    for r in co_rows:
        co_entities.append({
            "id": r[0],
            "canonical_name": r[1],
            "type": r[2],
            "weight": r[3],
            "shared_doc_ids": shared_docs.get(r[0], []),
        })

    # Central entity info
    entity = conn.execute(
        "SELECT id, canonical_name, type FROM entities WHERE id = ?", (entity_id,)
    ).fetchone()
    conn.close()

    if not entity:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Entity not found")

    return {
        "entity": {
            "id": entity[0],
            "canonical_name": entity[1],
            "type": entity[2],
            "source_count": len(doc_ids),
        },
        "documents": documents,
        "co_entities": co_entities,
    }


@router.get("/entities/{entity_id}")
def get_entity(entity_id: str):
    settings = get_settings()
    conn = get_connection(settings.db_path)
    entity = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
    if not entity:
        conn.close()
        raise HTTPException(status_code=404, detail="Entity not found")
    sources = conn.execute(
        "SELECT document_id, chunk_id, extraction_pass, spec_version, job_id FROM entity_sources WHERE entity_id = ?",
        (entity_id,),
    ).fetchall()
    merges = conn.execute("SELECT from_name FROM merge_map WHERE to_entity_id = ?", (entity_id,)).fetchall()
    conn.close()
    return {
        "id": entity["id"], "canonical_name": entity["canonical_name"], "type": entity["type"],
        "created_at": entity["created_at"],
        "sources": [{"document_id": s[0], "chunk_id": s[1], "extraction_pass": s[2], "spec_version": s[3], "job_id": s[4]} for s in sources],
        "merge_history": [m[0] for m in merges],
    }
