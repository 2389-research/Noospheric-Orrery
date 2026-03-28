from fastapi import APIRouter
from ..config import get_settings
from ..db import get_connection
from ..models import Stats

router = APIRouter()

@router.get("/stats", response_model=Stats)
def get_stats():
    settings = get_settings()
    conn = get_connection(settings.db_path)
    docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    entities = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    domains = conn.execute("SELECT COUNT(*) FROM domains WHERE document_count > 0").fetchone()[0]
    active = conn.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running')").fetchone()[0]
    conn.close()
    return Stats(document_count=docs, entity_count=entities, domain_count=domains, active_jobs=active)
