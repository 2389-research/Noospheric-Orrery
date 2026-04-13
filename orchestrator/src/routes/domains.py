import logging
from fastapi import APIRouter, Depends
from ..dependencies import get_auth_store, AuthStore

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/domains")
def list_domains(auth: AuthStore = Depends(get_auth_store)):
    store = auth.store
    domains = store.domains.list(min_doc_count=1)

    # Get per-domain text/image breakdown
    text_image_counts = {}
    try:
        rows = store.conn.execute("""
            SELECT dd.domain_path,
                   SUM(CASE WHEN d.content_type = 'image' THEN 1 ELSE 0 END) as image_count,
                   SUM(CASE WHEN d.content_type != 'image' OR d.content_type IS NULL THEN 1 ELSE 0 END) as text_count
            FROM document_domains dd
            JOIN documents d ON dd.document_id = d.id
            GROUP BY dd.domain_path
        """).fetchall()
        for r in rows:
            text_image_counts[r[0]] = {"text_count": r[2], "image_count": r[1]}
    except Exception:
        logger.warning("Failed to fetch text/image breakdown for domains", exc_info=True)

    store.close()
    result = []
    for d in domains:
        counts = text_image_counts.get(d.path, {"text_count": d.document_count, "image_count": 0})
        result.append({
            "id": d.id, "path": d.path, "parent_path": d.parent_path,
            "document_count": d.document_count, "spec_version": d.spec_version,
            "created_at": d.created_at,
            "text_count": counts["text_count"],
            "image_count": counts["image_count"],
        })
    return result
