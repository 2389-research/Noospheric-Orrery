# ABOUTME: Serve image files from local filesystem.
# ABOUTME: Used by the ImagePane to display uploaded images and thumbnails.

from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from ..dependencies import get_auth_store, AuthStore

router = APIRouter()

MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}


@router.get("/images/{document_id}")
def serve_image(document_id: str, auth: AuthStore = Depends(get_auth_store)):
    """Serve an image file by document ID."""
    store = auth.store
    doc = store.documents.get(document_id)
    store.close()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # doc.source_path holds the local filesystem path for the image
    source = getattr(doc, 'source_path', None) or getattr(doc, 'image_path', None)
    if source and Path(source).exists():
        suffix = Path(source).suffix.lower()
        return FileResponse(source, media_type=MEDIA_TYPES.get(suffix, "image/jpeg"))

    raise HTTPException(status_code=404, detail="Image file not found")


@router.get("/images/{document_id}/thumbnail")
def serve_thumbnail(document_id: str, auth: AuthStore = Depends(get_auth_store)):
    """Serve a thumbnail for an image document."""
    store = auth.store
    doc = store.documents.get(document_id)
    store.close()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Try thumbnail first, fall back to full image
    for path in [getattr(doc, 'thumbnail_path', None), getattr(doc, 'source_path', None), getattr(doc, 'image_path', None)]:
        if path and Path(path).exists():
            suffix = Path(path).suffix.lower()
            return FileResponse(path, media_type=MEDIA_TYPES.get(suffix, "image/jpeg"))

    raise HTTPException(status_code=404, detail="No image available")
