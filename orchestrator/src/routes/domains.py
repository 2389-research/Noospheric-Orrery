from fastapi import APIRouter
from ..repositories.factory import get_store

router = APIRouter()

@router.get("/domains")
def list_domains():
    store = get_store()
    domains = store.domains.list(min_doc_count=1)
    store.close()
    return [{"id": d.id, "path": d.path, "parent_path": d.parent_path,
             "document_count": d.document_count, "spec_version": d.spec_version,
             "created_at": d.created_at} for d in domains]
