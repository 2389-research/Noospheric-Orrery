from fastapi import APIRouter, HTTPException
from ..config import get_settings
from ..db import get_connection

router = APIRouter()

@router.get("/documents")
def list_documents(limit: int = 50, offset: int = 0):
    settings = get_settings()
    conn = get_connection(settings.db_path)
    rows = conn.execute(
        """SELECT d.id, d.title, d.status, d.created_at,
                  GROUP_CONCAT(dd.domain_path) as domains,
                  (SELECT COUNT(*) FROM entity_sources es WHERE es.document_id = d.id) as entity_count
           FROM documents d
           LEFT JOIN document_domains dd ON d.id = dd.document_id
           GROUP BY d.id
           ORDER BY d.created_at DESC
           LIMIT ? OFFSET ?""",
        (limit, offset),
    ).fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1], "status": r[2], "created_at": r[3],
             "domains": r[4].split(",") if r[4] else [], "entity_count": r[5]} for r in rows]

@router.get("/documents/{document_id}")
def get_document(document_id: str):
    settings = get_settings()
    conn = get_connection(settings.db_path)
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    if not doc:
        conn.close()
        raise HTTPException(status_code=404, detail="Document not found")
    domains = conn.execute("SELECT domain_path, is_primary, confidence FROM document_domains WHERE document_id = ?", (document_id,)).fetchall()
    entities = conn.execute("""SELECT DISTINCT e.id, e.canonical_name, e.type FROM entities e
        JOIN entity_sources es ON e.id = es.entity_id WHERE es.document_id = ?""", (document_id,)).fetchall()
    conn.close()
    return {"id": doc["id"], "title": doc["title"], "source_path": doc["source_path"],
            "content": doc["content"], "metadata": doc["metadata"], "status": doc["status"],
            "created_at": doc["created_at"],
            "domains": [{"path": d[0], "is_primary": bool(d[1]), "confidence": d[2]} for d in domains],
            "entities": [{"id": e[0], "canonical_name": e[1], "type": e[2]} for e in entities]}
