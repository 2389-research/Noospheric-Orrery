from fastapi import APIRouter, HTTPException, Depends
from ..dependencies import get_auth_store, AuthStore
from ..repositories.factory import get_store
from ..pipeline.embedding_normalizer import (
    run_batch_normalization,
    get_normalization_summary,
    get_review_queue,
    resolve_review,
)

router = APIRouter()


@router.post("/normalize")
def trigger_normalization(auth: AuthStore = Depends(get_auth_store)):
    store = auth.store
    try:
        results = run_batch_normalization(store)
    finally:
        store.close()
    return results


@router.get("/normalize/summary")
def normalization_summary(auth: AuthStore = Depends(get_auth_store)):
    store = auth.store
    try:
        return get_normalization_summary(store)
    finally:
        store.close()


@router.get("/normalize/review")
def review_queue(auth: AuthStore = Depends(get_auth_store)):
    store = auth.store
    try:
        return get_review_queue(store)
    finally:
        store.close()


@router.post("/normalize/review/{review_id}")
def resolve_review_item(review_id: str, action: str = "merge", auth: AuthStore = Depends(get_auth_store)):
    if action not in ("merge", "keep_separate"):
        raise HTTPException(status_code=400, detail="action must be 'merge' or 'keep_separate'")
    store = auth.store
    try:
        resolve_review(store, review_id, action)
    finally:
        store.close()
    return {"status": "resolved", "action": action}
