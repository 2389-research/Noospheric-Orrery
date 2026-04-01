"""Auth provisioning and invite endpoints for multi-tenancy."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from google.cloud import firestore

from ..auth import get_current_user, require_role, AuthUser
from ..auth_admin import set_user_claims, get_user_claims, signal_token_refresh


class InviteRequest(BaseModel):
    email: str
    role: str = "editor"  # editor | viewer

router = APIRouter()


def _get_firestore_db():
    """Get raw Firestore client (not workspace-scoped)."""
    return firestore.Client()


@router.post("/auth/provision")
async def provision_user(user: AuthUser = Depends(get_current_user)):
    """Create org + default workspace on first sign-in. Idempotent.

    Returns existing org if already provisioned.
    Safe to call on every sign-in.
    """
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
        "createdAt": firestore.SERVER_TIMESTAMP,
        "createdBy": user.uid,
    })

    # Add user as admin member
    org_ref.collection("members").document(user.uid).set({
        "role": "admin",
        "email": user.email,
        "joinedAt": firestore.SERVER_TIMESTAMP,
    })

    # Create default workspace
    ws_ref = db.collection("workspaces").document()
    ws_ref.set({
        "name": "Default",
        "orgId": org_id,
        "createdBy": user.uid,
        "createdAt": firestore.SERVER_TIMESTAMP,
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


# --- Invite flow ---


@router.post("/invites")
async def create_invite(
    req: InviteRequest,
    user: AuthUser = Depends(require_role("admin")),
):
    """Admin creates an invite. Invitee accepts on next sign-in."""
    if req.role not in ("editor", "viewer"):
        raise HTTPException(400, "role must be editor or viewer")

    db = _get_firestore_db()
    invite_ref = db.collection("invites").document()
    invite_ref.set({
        "email": req.email.lower(),
        "role": req.role,
        "orgId": user.org_id,
        "createdBy": user.uid,
        "createdAt": firestore.SERVER_TIMESTAMP,
        "status": "pending",
    })
    return {"inviteId": invite_ref.id, "email": req.email, "role": req.role}


@router.get("/invites")
async def list_invites(user: AuthUser = Depends(require_role("admin"))):
    """List pending invites for this org."""
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
            "joinedAt": firestore.SERVER_TIMESTAMP,
        })

    # Set claims
    set_user_claims(user.uid, org_id, role)
    signal_token_refresh(db, user.uid)

    # Mark invite consumed
    invite_doc.reference.update({"status": "accepted"})

    return {"invited": True, "orgId": org_id, "role": role}
