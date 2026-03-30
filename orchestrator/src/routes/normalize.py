from fastapi import APIRouter, HTTPException
from ..repositories.factory import get_store
from ..pipeline.embedding_normalizer import (
    run_batch_normalization,
    get_normalization_summary,
    get_review_queue,
    resolve_review,
)

router = APIRouter()


@router.post("/normalize")
def trigger_normalization():
    store = get_store()
    try:
        results = run_batch_normalization(store)
    finally:
        store.close()
    return results


@router.get("/normalize/summary")
def normalization_summary():
    store = get_store()
    try:
        return get_normalization_summary(store)
    finally:
        store.close()


@router.get("/normalize/review")
def review_queue():
    store = get_store()
    try:
        return get_review_queue(store)
    finally:
        store.close()


@router.post("/normalize/review/{review_id}")
def resolve_review_item(review_id: str, action: str = "merge"):
    if action not in ("merge", "keep_separate"):
        raise HTTPException(status_code=400, detail="action must be 'merge' or 'keep_separate'")
    store = get_store()
    try:
        resolve_review(store, review_id, action)
    finally:
        store.close()
    return {"status": "resolved", "action": action}
