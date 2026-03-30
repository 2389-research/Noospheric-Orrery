from fastapi import APIRouter
from ..models import Stats
from ..repositories.factory import get_store

router = APIRouter()

@router.get("/stats", response_model=Stats)
def get_stats():
    store = get_store()
    result = Stats(
        document_count=store.documents.count(),
        entity_count=store.entities.count(),
        domain_count=len(store.domains.list(min_doc_count=1)),
        active_jobs=store.jobs.count_active(),
    )
    store.close()
    return result
