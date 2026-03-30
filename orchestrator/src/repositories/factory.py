"""Factory for creating the appropriate DataStore.

Usage:
    from repositories.factory import get_store
    store = get_store()  # reads DB_BACKEND env var

Testing:
    from repositories.factory import set_test_store
    set_test_store(my_test_store)  # all get_store() calls return this
"""

import os
from .interfaces import DataStore

_test_store: DataStore | None = None


def set_test_store(store: DataStore | None) -> None:
    """Override get_store() for testing. Pass None to reset."""
    global _test_store
    _test_store = store


def get_store(db_path: str | None = None, workspace_id: str | None = None) -> DataStore:
    """Create a DataStore based on DB_BACKEND env var.

    Args:
        db_path: SQLite database path (SQLite only)
        workspace_id: Firestore workspace ID (overrides env var, from auth user)

    If a test store is set, returns that instead.
    """
    if _test_store is not None:
        return _test_store

    backend = os.environ.get("DB_BACKEND", "sqlite").lower()

    if backend == "sqlite":
        from .sqlite_store import SQLiteDataStore
        if not db_path:
            from ..config import get_settings
            db_path = get_settings().db_path
        return SQLiteDataStore(db_path)

    elif backend == "firestore":
        from .firestore_store import FirestoreDataStore
        project_id = os.environ.get("FIREBASE_PROJECT_ID", "noospheric-orrery")
        ws_id = workspace_id or os.environ.get("FIREBASE_WORKSPACE_ID", "default")
        return FirestoreDataStore(project_id=project_id, workspace_id=ws_id)

    else:
        raise ValueError(f"Unknown DB_BACKEND: {backend}. Use 'sqlite' or 'firestore'.")
