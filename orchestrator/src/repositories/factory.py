"""Factory for creating the appropriate DataStore.

Usage:
    from repositories.factory import get_store
    store = get_store()  # reads DB_BACKEND env var
"""

import os
from .interfaces import DataStore


def get_store(db_path: str | None = None) -> DataStore:
    """Create a DataStore based on DB_BACKEND env var.

    DB_BACKEND=sqlite (default): uses SQLite at db_path
    DB_BACKEND=firestore: uses Firestore (requires firebase credentials)
    """
    backend = os.environ.get("DB_BACKEND", "sqlite").lower()

    if backend == "sqlite":
        from .sqlite_store import SQLiteDataStore
        if not db_path:
            from ..config import get_settings
            db_path = get_settings().db_path
        return SQLiteDataStore(db_path)

    elif backend == "firestore":
        # TODO: implement FirestoreDataStore
        raise NotImplementedError("Firestore backend not yet implemented. Set DB_BACKEND=sqlite.")

    else:
        raise ValueError(f"Unknown DB_BACKEND: {backend}. Use 'sqlite' or 'firestore'.")
