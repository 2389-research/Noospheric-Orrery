from __future__ import annotations
"""Factory for creating the appropriate DataStore.

Usage:
    from repositories.factory import get_store
    store = get_store()  # reads DB_BACKEND env var

SQLite multi-workspace: each workspace gets its own .db file under
~/orrery-data/workspaces/{workspace_id}/orrery.db

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


def _sqlite_workspace_db_path(workspace_id: str | None) -> str:
    """Get the SQLite database path for a workspace.

    Multi-workspace layout:
      {data_dir}/workspaces/default/orrery.db
      {data_dir}/workspaces/abc123/orrery.db
    """
    from ..config import get_settings
    settings = get_settings()

    ws_id = workspace_id or "default"
    base_dir = os.path.dirname(settings.db_path)
    ws_dir = os.path.join(base_dir, "workspaces", ws_id)
    os.makedirs(ws_dir, exist_ok=True)
    return os.path.join(ws_dir, "orrery.db")


def get_store(db_path: str | None = None, workspace_id: str | None = None) -> DataStore:
    """Create a DataStore based on DB_BACKEND env var.

    Args:
        db_path: SQLite database path (overrides workspace routing)
        workspace_id: Workspace ID — routes to workspace-specific DB (SQLite) or collection (Firestore)

    If a test store is set, returns that instead.
    """
    if _test_store is not None:
        return _test_store

    backend = os.environ.get("DB_BACKEND", "sqlite").lower()

    if backend == "sqlite":
        from .sqlite_store import SQLiteDataStore
        if not db_path:
            db_path = _sqlite_workspace_db_path(workspace_id)
        return SQLiteDataStore(db_path)

    elif backend == "firestore":
        from .firestore_store import FirestoreDataStore
        project_id = os.environ.get("FIREBASE_PROJECT_ID", "noospheric-orrery")
        ws_id = workspace_id or os.environ.get("FIREBASE_WORKSPACE_ID")
        if not ws_id:
            raise ValueError("Firestore backend requires a workspace ID (X-Workspace-Id header or FIREBASE_WORKSPACE_ID env var)")
        return FirestoreDataStore(project_id=project_id, workspace_id=ws_id)

    else:
        raise ValueError(f"Unknown DB_BACKEND: {backend}. Use 'sqlite' or 'firestore'.")
