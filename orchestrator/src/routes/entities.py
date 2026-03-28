from fastapi import APIRouter, HTTPException
from ..config import get_settings
from ..db import get_connection

router = APIRouter()

@router.get("/entities")
def list_entities(limit: int = 50, offset: int = 0, type: str | None = None, domain: str | None = None):
    settings = get_settings()
    conn = get_connection(settings.db_path)
    query = "SELECT e.id, e.canonical_name, e.type, (SELECT COUNT(*) FROM entity_sources es WHERE es.entity_id = e.id) as source_count FROM entities e"
    params: list = []
    conditions = []
    if domain:
        query += " JOIN entity_sources es2 ON e.id = es2.entity_id JOIN document_domains dd ON es2.document_id = dd.document_id AND dd.domain_path = ?"
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

@router.get("/entities/{entity_id}")
def get_entity(entity_id: str):
    settings = get_settings()
    conn = get_connection(settings.db_path)
    entity = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
    if not entity:
        conn.close()
        raise HTTPException(status_code=404, detail="Entity not found")
    sources = conn.execute("SELECT document_id, chunk_id, extraction_pass, spec_version FROM entity_sources WHERE entity_id = ?", (entity_id,)).fetchall()
    merges = conn.execute("SELECT from_name FROM merge_map WHERE to_entity_id = ?", (entity_id,)).fetchall()
    conn.close()
    return {"id": entity["id"], "canonical_name": entity["canonical_name"], "type": entity["type"],
            "created_at": entity["created_at"],
            "sources": [{"document_id": s[0], "chunk_id": s[1], "extraction_pass": s[2], "spec_version": s[3]} for s in sources],
            "merge_history": [m[0] for m in merges]}
