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

from dataclasses import dataclass
from fastapi import Depends
from .auth import get_current_user, AuthUser
from .repositories.factory import get_store
from .repositories.interfaces import DataStore


@dataclass
class AuthStore:
    """Authenticated data store — bundles user context with workspace-scoped store."""
    user: AuthUser
    store: DataStore


async def get_auth_store(user: AuthUser = Depends(get_current_user)) -> AuthStore:
    """Get a DataStore scoped to the authenticated user's workspace."""
    store = get_store(workspace_id=user.workspace_id)
    return AuthStore(user=user, store=store)
