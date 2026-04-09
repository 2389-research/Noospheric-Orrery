# ABOUTME: Firebase Storage helpers for uploading/downloading images.
# ABOUTME: Used in cloud mode; local mode uses filesystem paths directly.

import os
from pathlib import Path

_bucket = None


def _get_bucket():
    """Lazy-init Firebase Storage bucket."""
    global _bucket
    if _bucket is None:
        from firebase_admin import storage
        bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET", "noospheric-orrery.firebasestorage.app")
        _bucket = storage.bucket(bucket_name)
    return _bucket


def upload_image(local_path: str, storage_path: str) -> str:
    """Upload a local image to Firebase Storage. Returns the storage path."""
    bucket = _get_bucket()
    blob = bucket.blob(storage_path)
    blob.upload_from_filename(local_path)
    return storage_path


def download_image_bytes(storage_path: str) -> tuple[bytes, str]:
    """Download image bytes from Firebase Storage. Returns (bytes, content_type)."""
    bucket = _get_bucket()
    blob = bucket.blob(storage_path)
    data = blob.download_as_bytes()
    content_type = blob.content_type or "image/jpeg"
    return data, content_type


def image_exists(storage_path: str) -> bool:
    """Check if an image exists in Firebase Storage."""
    bucket = _get_bucket()
    blob = bucket.blob(storage_path)
    return blob.exists()
