from fastapi import APIRouter, HTTPException
from ..config import get_settings
from ..db import get_connection
from ..pipeline.embedding_normalizer import (
    run_batch_normalization,
    get_normalization_summary,
    get_review_queue,
    resolve_review,
)

router = APIRouter()


@router.post("/normalize")
def trigger_normalization():
    """Run the full normalization cascade on all entities."""
    settings = get_settings()
    conn = get_connection(settings.db_path)
    try:
        results = run_batch_normalization(conn)
    finally:
        conn.close()
    return results


@router.get("/normalize/summary")
def normalization_summary():
    """Get summary of all normalization merges."""
    settings = get_settings()
    conn = get_connection(settings.db_path)
    try:
        return get_normalization_summary(conn)
    finally:
        conn.close()


@router.get("/normalize/review")
def review_queue():
    """Get pending ambiguous pairs for manual review."""
    settings = get_settings()
    conn = get_connection(settings.db_path)
    try:
        return get_review_queue(conn)
    finally:
        conn.close()


@router.post("/normalize/review/{review_id}")
def resolve_review_item(review_id: str, action: str = "merge"):
    """Resolve a review queue item. action = 'merge' or 'keep_separate'."""
    if action not in ("merge", "keep_separate"):
        raise HTTPException(status_code=400, detail="action must be 'merge' or 'keep_separate'")
    settings = get_settings()
    conn = get_connection(settings.db_path)
    try:
        resolve_review(conn, review_id, action)
    finally:
        conn.close()
    return {"status": "resolved", "action": action}
