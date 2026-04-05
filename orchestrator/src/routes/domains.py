from fastapi import APIRouter, Depends
from ..dependencies import get_auth_store, AuthStore

router = APIRouter()

@router.get("/domains")
def list_domains(auth: AuthStore = Depends(get_auth_store)):
    store = auth.store
    domains = store.domains.list(min_doc_count=1)
    store.close()
    return [{"id": d.id, "path": d.path, "parent_path": d.parent_path,
             "document_count": d.document_count, "spec_version": d.spec_version,
             "created_at": d.created_at} for d in domains]
