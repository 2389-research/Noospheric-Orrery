"""Auth provisioning endpoints.

Returns workspace list from the local JSON registry.
Invite endpoints are no-ops in local mode (preserved for API compatibility).
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import get_current_user, require_role, AuthUser

router = APIRouter()


class InviteRequest(BaseModel):
    email: str
    role: str = "editor"


@router.post("/auth/provision")
async def provision_user(user: AuthUser = Depends(get_current_user)):
    """Return workspace list from local registry. Idempotent."""
    from .workspace_routes import _load_registry
    registry = _load_registry()
    workspaces = [{"id": ws["id"], "name": ws["name"]} for ws in registry if ws.get("status") != "archived"]
    return {
        "orgId": "local",
        "role": "admin",
        "workspaces": workspaces,
    }


# --- Invite stubs (no-ops for local mode, preserved for API compat) ---

@router.post("/invites")
async def create_invite(req: InviteRequest, user: AuthUser = Depends(require_role("admin"))):
    return {"inviteId": "local", "email": req.email, "role": req.role}


@router.get("/invites")
async def list_invites(user: AuthUser = Depends(require_role("admin"))):
    return []


@router.delete("/invites/{invite_id}")
async def revoke_invite(invite_id: str, user: AuthUser = Depends(require_role("admin"))):
    return {"revoked": True}


@router.post("/auth/accept-invite")
async def accept_invite(user: AuthUser = Depends(get_current_user)):
    return {"invited": False}
