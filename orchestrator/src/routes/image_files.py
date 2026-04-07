# ABOUTME: Serve image files from the data volume for the frontend.
# ABOUTME: Used by the ImagePane to display uploaded images and thumbnails.

from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from ..dependencies import get_auth_store, AuthStore

router = APIRouter()


@router.get("/images/{document_id}")
def serve_image(document_id: str, auth: AuthStore = Depends(get_auth_store)):
    """Serve an image file by document ID."""
    store = auth.store
    doc = store.documents.get(document_id)
    store.close()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.content_type != "image":
        raise HTTPException(status_code=400, detail="Not an image document")

    # Try image_path first, then thumbnail
    image_path = doc.image_path
    if image_path and Path(image_path).exists():
        suffix = Path(image_path).suffix.lower()
        media_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}
        return FileResponse(image_path, media_type=media_types.get(suffix, "image/jpeg"))

    raise HTTPException(status_code=404, detail="Image file not found")


@router.get("/images/{document_id}/thumbnail")
def serve_thumbnail(document_id: str, auth: AuthStore = Depends(get_auth_store)):
    """Serve a thumbnail for an image document."""
    store = auth.store
    doc = store.documents.get(document_id)
    store.close()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.thumbnail_path and Path(doc.thumbnail_path).exists():
        return FileResponse(doc.thumbnail_path, media_type="image/jpeg")

    # Fall back to full image
    if doc.image_path and Path(doc.image_path).exists():
        return FileResponse(doc.image_path, media_type="image/jpeg")

    raise HTTPException(status_code=404, detail="No image available")
