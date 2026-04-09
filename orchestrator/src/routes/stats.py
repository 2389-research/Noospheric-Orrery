from fastapi import APIRouter, Depends
from ..models import Stats
from ..dependencies import get_auth_store, AuthStore

router = APIRouter()

@router.get("/stats", response_model=Stats)
def get_stats(auth: AuthStore = Depends(get_auth_store)):
    store = auth.store
    # Image count — check content_type if available
    image_count = 0
    try:
        if hasattr(store.documents, '_conn'):
            image_count = store.documents._conn.execute(
                "SELECT COUNT(*) FROM documents WHERE content_type = 'image'"
            ).fetchone()[0]
    except Exception:
        pass
    result = Stats(
        document_count=store.documents.count(),
        entity_count=store.entities.count(),
        domain_count=len(store.domains.list(min_doc_count=1)),
        active_jobs=store.jobs.count_active(),
        image_count=image_count,
    )
    store.close()
    return result
