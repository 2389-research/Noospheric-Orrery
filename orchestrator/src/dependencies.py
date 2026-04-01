from __future__ import annotations
"""FastAPI dependencies for authenticated data access.

Usage:
    from .dependencies import get_auth_store, AuthStore

    @router.get("/data")
    def get_data(auth: AuthStore = Depends(get_auth_store)):
        store = auth.store
        user = auth.user
        ...
        store.close()
"""

import os
from dataclasses import dataclass
from fastapi import Depends, Header, HTTPException
from .auth import get_current_user, AuthUser
from .repositories.factory import get_store
from .repositories.interfaces import DataStore


@dataclass
class AuthStore:
    """Authenticated data store — bundles user context with workspace-scoped store."""
    user: AuthUser
    store: DataStore


async def validate_workspace(
    user: AuthUser = Depends(get_current_user),
    x_workspace_id: str | None = Header(default=None),
) -> AuthUser:
    """Validate X-Workspace-Id header belongs to user's org. Updates user.workspace_id.

    Falls back to user.workspace_id if header not provided (backwards compat).
    Skips validation in local dev mode (no org_id set).
    """
    if x_workspace_id:
        user.workspace_id = x_workspace_id

    # Skip org validation in local dev mode or when user has no org yet
    if not user.org_id:
        return user

    # Validate workspace belongs to user's org
    backend = os.environ.get("DB_BACKEND", "sqlite").lower()
    if backend == "firestore":
        from google.cloud import firestore
        db = firestore.Client()
        ws_doc = db.collection("workspaces").document(user.workspace_id).get()
        if not ws_doc.exists:
            raise HTTPException(404, "Workspace not found")
        ws_data = ws_doc.to_dict()
        if ws_data.get("orgId") and ws_data["orgId"] != user.org_id:
            raise HTTPException(403, "Workspace does not belong to your org")

    return user


async def get_auth_store(user: AuthUser = Depends(validate_workspace)) -> AuthStore:
    """Get a DataStore scoped to the authenticated user's workspace."""
    store = get_store(workspace_id=user.workspace_id)
    return AuthStore(user=user, store=store)
