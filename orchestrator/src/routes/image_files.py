# ABOUTME: Serve image files — from local filesystem (SQLite) or Firebase Storage (cloud).
# ABOUTME: Used by the ImagePane to display uploaded images and thumbnails.

import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse, Response
from ..dependencies import get_auth_store, AuthStore

router = APIRouter()

MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}


def _serve_from_storage(storage_path: str):
    """Download from Firebase Storage and return as Response."""
    from ..services.image_storage import download_image_bytes, image_exists
    if not image_exists(storage_path):
        return None
    data, content_type = download_image_bytes(storage_path)
    return Response(content=data, media_type=content_type)


def _serve_local(file_path: str):
    """Serve from local filesystem."""
    if file_path and Path(file_path).exists():
        suffix = Path(file_path).suffix.lower()
        return FileResponse(file_path, media_type=MEDIA_TYPES.get(suffix, "image/jpeg"))
    return None


def _is_cloud():
    return os.environ.get("DB_BACKEND", "sqlite").lower() == "firestore"


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

    # Try local path first (works for both modes when files exist locally)
    resp = _serve_local(doc.image_path)
    if resp:
        return resp

    # Cloud mode: try Firebase Storage
    if _is_cloud() and doc.image_path:
        resp = _serve_from_storage(doc.image_path)
        if resp:
            return resp

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
    for path in [doc.thumbnail_path, doc.image_path]:
        if not path:
            continue
        resp = _serve_local(path)
        if resp:
            return resp
        if _is_cloud():
            resp = _serve_from_storage(path)
            if resp:
                return resp

    raise HTTPException(status_code=404, detail="No image available")
