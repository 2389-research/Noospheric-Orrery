from fastapi import APIRouter, HTTPException
from ..repositories.factory import get_store

router = APIRouter()

@router.get("/documents")
def list_documents(limit: int = 50, offset: int = 0):
    store = get_store()
    docs = store.documents.list(limit=limit, offset=offset)
    result = []
    for d in docs:
        entity_count = len(store.entities.get_for_document(d.id)) if d.id else 0
        result.append({
            "id": d.id, "title": d.title, "status": d.status, "created_at": d.created_at,
            "domains": d.domains, "entity_count": entity_count,
        })
    store.close()
    return result

@router.get("/documents/{document_id}")
def get_document(document_id: str):
    store = get_store()
    doc = store.documents.get(document_id)
    if not doc:
        store.close()
        raise HTTPException(status_code=404, detail="Document not found")
    domains = store.domains.get_domains_for_document(document_id)
    entities = store.entities.get_for_document(document_id)
    store.close()
    return {
        "id": doc.id, "title": doc.title, "source_path": doc.source_path,
        "content": doc.content, "status": doc.status, "created_at": doc.created_at,
        "domains": [{"path": d.domain_path, "is_primary": d.is_primary, "confidence": d.confidence} for d in domains],
        "entities": [{"id": e.id, "canonical_name": e.canonical_name, "type": e.type} for e in entities],
    }
