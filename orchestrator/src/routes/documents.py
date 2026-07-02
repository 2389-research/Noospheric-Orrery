import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse, PlainTextResponse
from ..dependencies import get_auth_store, AuthStore
from ..repositories.factory import get_store
from ..pipeline.file_extractor import (
    TEXT_EXTENSIONS, PDF_EXTENSIONS, DOCX_EXTENSIONS, NOTEBOOK_EXTENSIONS,
)
from .image_files import MEDIA_TYPES, serve_image

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/documents")
def list_documents(limit: int = 50, offset: int = 0, auth: AuthStore = Depends(get_auth_store)):
    store = auth.store
    docs = store.documents.list(limit=limit, offset=offset)
    result = []
    for d in docs:
        entity_count = len(store.entities.get_for_document(d.id)) if d.id else 0
        result.append({
            "id": d.id, "title": d.title, "status": d.status, "created_at": d.created_at,
            "domains": d.domains, "entity_count": entity_count,
            "content_type": d.content_type,
        })
    store.close()
    return result

@router.get("/documents/{document_id}")
def get_document(document_id: str, auth: AuthStore = Depends(get_auth_store)):
    store = auth.store
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
        "content_type": doc.content_type,
        "domains": [{"path": d.domain_path, "is_primary": d.is_primary, "confidence": d.confidence} for d in domains],
        "entities": [{"id": e.id, "canonical_name": e.canonical_name, "type": e.type} for e in entities],
    }


@router.delete("/documents/{document_id}")
def delete_document(document_id: str, auth: AuthStore = Depends(get_auth_store)):
    store = auth.store
    doc = store.documents.get(document_id)
    if not doc:
        store.close()
        raise HTTPException(status_code=404, detail="Document not found")

    result = store.documents.delete(document_id)
    store.close()

    for path in (doc.source_path, getattr(doc, "thumbnail_path", None)):
        try:
            if path and Path(path).exists():
                os.remove(path)
        except OSError as e:
            logger.warning("Failed to remove file %s for document %s: %s", path, document_id, e)

    return {"deleted": True, "entities_removed": result.get("entities_removed", [])}


@router.get("/documents/{document_id}/file")
def serve_document_file(document_id: str, auth: AuthStore = Depends(get_auth_store)):
    store = auth.store
    doc = store.documents.get(document_id)

    if not doc:
        store.close()
        raise HTTPException(status_code=404, detail="Document not found")

    suffix = Path(doc.source_path).suffix.lower() if doc.source_path else ""

    if suffix in MEDIA_TYPES:
        # serve_image looks up the document itself and closes the store.
        return serve_image(document_id, auth=auth)

    store.close()

    if suffix in PDF_EXTENSIONS or suffix in DOCX_EXTENSIONS:
        return PlainTextResponse(doc.content or "")

    if suffix in NOTEBOOK_EXTENSIONS:
        if not doc.source_path or not Path(doc.source_path).exists():
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(doc.source_path, media_type="application/json")

    if suffix in TEXT_EXTENSIONS or not suffix:
        if not doc.source_path or not Path(doc.source_path).exists():
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(doc.source_path, media_type="text/plain")

    raise HTTPException(status_code=404, detail="File not found")
