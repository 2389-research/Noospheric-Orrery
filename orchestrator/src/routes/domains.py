from fastapi import APIRouter
from ..config import get_settings
from ..db import get_connection

router = APIRouter()

@router.get("/domains")
def list_domains():
    settings = get_settings()
    conn = get_connection(settings.db_path)
    rows = conn.execute("SELECT id, path, parent_path, document_count, spec_version, created_at FROM domains WHERE document_count > 0 ORDER BY path").fetchall()
    conn.close()
    return [{"id": r[0], "path": r[1], "parent_path": r[2], "document_count": r[3], "spec_version": r[4], "created_at": r[5]} for r in rows]
