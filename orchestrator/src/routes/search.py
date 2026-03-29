"""Search endpoint — hybrid FAISS + graph search with RRF fusion."""

from fastapi import APIRouter
from ..config import get_settings
from ..db import get_connection
from ..pipeline.search import search, build_indexes

router = APIRouter()
_indexes_built = False


@router.get("/search")
def search_query(q: str, top_k: int = 20):
    """Search entities and chunks. Returns fused results."""
    global _indexes_built
    settings = get_settings()
    conn = get_connection(settings.db_path)

    if not _indexes_built:
        stats = build_indexes(conn)
        _indexes_built = True

    results = search(conn, q, top_k=top_k)
    conn.close()
    return results


@router.post("/search/rebuild")
def rebuild_search_index():
    """Rebuild FAISS indexes from current DB state."""
    global _indexes_built
    settings = get_settings()
    conn = get_connection(settings.db_path)
    stats = build_indexes(conn)
    _indexes_built = True
    conn.close()
    return {"status": "rebuilt", **stats}
