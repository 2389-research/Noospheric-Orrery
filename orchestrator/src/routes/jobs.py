from fastapi import APIRouter
from ..config import get_settings
from ..db import get_connection

router = APIRouter()

@router.get("/jobs")
def list_jobs(status: str | None = None):
    settings = get_settings()
    conn = get_connection(settings.db_path)
    if status:
        rows = conn.execute("SELECT id, type, target, status, created_at, started_at, completed_at FROM jobs WHERE status = ? ORDER BY created_at DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT id, type, target, status, created_at, started_at, completed_at FROM jobs ORDER BY created_at DESC").fetchall()
    conn.close()
    return [{"id": r[0], "type": r[1], "target": r[2], "status": r[3], "created_at": r[4], "started_at": r[5], "completed_at": r[6]} for r in rows]
