from fastapi import APIRouter, Depends
from ..models import Stats
from ..dependencies import get_auth_store, AuthStore

router = APIRouter()

@router.get("/stats", response_model=Stats)
def get_stats(auth: AuthStore = Depends(get_auth_store)):
    store = auth.store
    result = Stats(
        document_count=store.documents.count(),
        entity_count=store.entities.count(),
        domain_count=len(store.domains.list(min_doc_count=1)),
        active_jobs=store.jobs.count_active(),
    )
    store.close()
    return result
