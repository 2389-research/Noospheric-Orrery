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

from dataclasses import dataclass
from fastapi import Depends, Header, Request
from .auth import get_current_user, AuthUser
from .repositories.factory import get_store
from .repositories.interfaces import DataStore


def query_id(request: Request) -> str:
    """The per-request correlation id minted by QueryIdMiddleware (issue #93). Capture-relevant
    READ routes depend on this and include it in their JSON body, so a session log (MCP or a bare
    curl) can correlate the call to the graph nodes it returned. Falls back to '' if the middleware
    isn't in the stack (e.g. a direct ASGI test)."""
    return getattr(request.state, "query_id", "") or ""


@dataclass
class AuthStore:
    """Authenticated data store — bundles user context with workspace-scoped store."""
    user: AuthUser
    store: DataStore


async def validate_workspace(
    user: AuthUser = Depends(get_current_user),
    x_workspace_id: str | None = Header(default=None),
) -> AuthUser:
    """Validate X-Workspace-Id header. Updates user.workspace_id."""
    if x_workspace_id:
        user.workspace_id = x_workspace_id
    return user


async def get_auth_store(user: AuthUser = Depends(validate_workspace)) -> AuthStore:
    """Get a DataStore scoped to the authenticated user's workspace."""
    store = get_store(workspace_id=user.workspace_id)
    return AuthStore(user=user, store=store)
