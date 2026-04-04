"""Auth provisioning and invite endpoints for multi-tenancy."""

import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import get_current_user, require_role, AuthUser

def _is_sqlite():
    return os.environ.get("DB_BACKEND", "sqlite").lower() == "sqlite"


class InviteRequest(BaseModel):
    email: str
    role: str = "editor"  # editor | viewer

router = APIRouter()


_firestore = None

def _get_firestore_module():
    global _firestore
    if _firestore is None:
        from google.cloud import firestore
        _firestore = firestore
    return _firestore

def _get_firestore_db():
    """Get raw Firestore client (not workspace-scoped)."""
    return _get_firestore_module().Client()


@router.post("/auth/provision")
async def provision_user(user: AuthUser = Depends(get_current_user)):
    """Create org + default workspace on first sign-in. Idempotent.

    In SQLite mode, returns a fixed local session.
    """
    if _is_sqlite():
        from .workspace_routes import _load_registry
        registry = _load_registry()
        workspaces = [{"id": ws["id"], "name": ws["name"]} for ws in registry if ws.get("status") != "archived"]
        return {
            "orgId": "local",
            "role": "admin",
            "workspaces": workspaces,
        }

    from ..auth_admin import set_user_claims, get_user_claims, signal_token_refresh
    db = _get_firestore_db()
    claims = get_user_claims(user.uid)

    if claims.get("orgId"):
        # Already provisioned — return existing workspaces
        workspaces = (
            db.collection("workspaces")
            .where("orgId", "==", claims["orgId"])
            .stream()
        )
        ws_list = [{"id": ws.id, **ws.to_dict()} for ws in workspaces if ws.to_dict().get("status") != "archived"]
        return {
            "orgId": claims["orgId"],
            "role": claims.get("role", "editor"),
            "workspaces": ws_list,
        }

    # New user — create org
    org_ref = db.collection("organizations").document()
    org_id = org_ref.id
    org_name = (user.email or "User").split("@")[0].replace(".", " ").title() + "'s Org"

    org_ref.set({
        "name": org_name,
        "createdAt": _get_firestore_module().SERVER_TIMESTAMP,
        "createdBy": user.uid,
    })

    # Add user as admin member
    org_ref.collection("members").document(user.uid).set({
        "role": "admin",
        "email": user.email,
        "joinedAt": _get_firestore_module().SERVER_TIMESTAMP,
    })

    # Create default workspace
    ws_ref = db.collection("workspaces").document()
    ws_ref.set({
        "name": "Default",
        "orgId": org_id,
        "createdBy": user.uid,
        "createdAt": _get_firestore_module().SERVER_TIMESTAMP,
        "description": "",
    })

    # Set claims on user JWT
    set_user_claims(user.uid, org_id, "admin")
    signal_token_refresh(db, user.uid)

    return {
        "orgId": org_id,
        "role": "admin",
        "workspaces": [{"id": ws_ref.id, "name": "Default"}],
    }


# --- Invite flow (Firestore only — no-ops in SQLite mode) ---


@router.post("/invites")
async def create_invite(
    req: InviteRequest,
    user: AuthUser = Depends(require_role("admin")),
):
    """Admin creates an invite. Invitee accepts on next sign-in."""
    if _is_sqlite():
        return {"inviteId": "local", "email": req.email, "role": req.role}
    if req.role not in ("editor", "viewer"):
        raise HTTPException(400, "role must be editor or viewer")

    from google.cloud import firestore
    db = _get_firestore_db()
    invite_ref = db.collection("invites").document()
    invite_ref.set({
        "email": req.email.lower(),
        "role": req.role,
        "orgId": user.org_id,
        "createdBy": user.uid,
        "createdAt": _get_firestore_module().SERVER_TIMESTAMP,
        "status": "pending",
    })
    return {"inviteId": invite_ref.id, "email": req.email, "role": req.role}


@router.get("/invites")
async def list_invites(user: AuthUser = Depends(require_role("admin"))):
    """List pending invites for this org."""
    if _is_sqlite():
        return []
    db = _get_firestore_db()
    invites = (
        db.collection("invites")
        .where("orgId", "==", user.org_id)
        .where("status", "==", "pending")
        .stream()
    )
    return [{"id": inv.id, **inv.to_dict()} for inv in invites]


@router.delete("/invites/{invite_id}")
async def revoke_invite(
    invite_id: str,
    user: AuthUser = Depends(require_role("admin")),
):
    if _is_sqlite():
        return {"revoked": True}
    db = _get_firestore_db()
    invite_ref = db.collection("invites").document(invite_id)
    invite = invite_ref.get().to_dict()
    if not invite or invite.get("orgId") != user.org_id:
        raise HTTPException(404, "Invite not found")
    invite_ref.update({"status": "revoked"})
    return {"revoked": True}


@router.post("/auth/accept-invite")
async def accept_invite(user: AuthUser = Depends(get_current_user)):
    """Called after sign-in for new users. Checks for pending invite matching their email."""
    if _is_sqlite():
        return {"invited": False}
    from ..auth_admin import get_user_claims, set_user_claims, signal_token_refresh
    claims = get_user_claims(user.uid)
    if claims.get("orgId"):
        return {"invited": False, "alreadyProvisioned": True}

    db = _get_firestore_db()
    invites = (
        db.collection("invites")
        .where("email", "==", (user.email or "").lower())
        .where("status", "==", "pending")
        .limit(1)
        .stream()
    )
    invite_list = list(invites)

    if not invite_list:
        return {"invited": False}

    invite_doc = invite_list[0]
    invite = invite_doc.to_dict()
    org_id = invite["orgId"]
    role = invite["role"]

    # Add member to org
    db.collection("organizations").document(org_id) \
        .collection("members").document(user.uid).set({
            "role": role,
            "email": user.email,
            "joinedAt": _get_firestore_module().SERVER_TIMESTAMP,
        })

    # Set claims
    set_user_claims(user.uid, org_id, role)
    signal_token_refresh(db, user.uid)

    # Mark invite consumed
    invite_doc.reference.update({"status": "accepted"})

    return {"invited": True, "orgId": org_id, "role": role}
