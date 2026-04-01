"""Workspace CRUD endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from google.cloud import firestore

from ..auth import AuthUser, require_role

router = APIRouter()


def _get_firestore_db():
    return firestore.Client()


class CreateWorkspaceRequest(BaseModel):
    name: str
    description: str = ""


class RenameWorkspaceRequest(BaseModel):
    name: str


@router.post("/workspaces")
async def create_workspace(
    req: CreateWorkspaceRequest,
    user: AuthUser = Depends(require_role("admin")),
):
    db = _get_firestore_db()
    ws_ref = db.collection("workspaces").document()
    ws_ref.set({
        "name": req.name,
        "description": req.description,
        "orgId": user.org_id,
        "createdBy": user.uid,
        "createdAt": firestore.SERVER_TIMESTAMP,
    })
    return {"workspaceId": ws_ref.id, "name": req.name}


@router.get("/workspaces")
async def list_workspaces(user: AuthUser = Depends(require_role("viewer"))):
    """Return all active workspaces for the user's org."""
    db = _get_firestore_db()
    workspaces = (
        db.collection("workspaces")
        .where("orgId", "==", user.org_id)
        .stream()
    )
    return [
        {"id": ws.id, **ws.to_dict()}
        for ws in workspaces
        if ws.to_dict().get("status") != "archived"
    ]


@router.patch("/workspaces/{workspace_id}")
async def rename_workspace(
    workspace_id: str,
    req: RenameWorkspaceRequest,
    user: AuthUser = Depends(require_role("admin")),
):
    db = _get_firestore_db()
    ws_ref = db.collection("workspaces").document(workspace_id)
    ws = ws_ref.get().to_dict()
    if not ws or ws.get("orgId") != user.org_id:
        raise HTTPException(404, "Workspace not found")
    ws_ref.update({"name": req.name})
    return {"updated": True}


@router.delete("/workspaces/{workspace_id}")
async def archive_workspace(
    workspace_id: str,
    user: AuthUser = Depends(require_role("admin")),
):
    """Soft delete — sets status to archived."""
    db = _get_firestore_db()
    ws_ref = db.collection("workspaces").document(workspace_id)
    ws = ws_ref.get().to_dict()
    if not ws or ws.get("orgId") != user.org_id:
        raise HTTPException(404, "Workspace not found")
    ws_ref.update({"status": "archived", "archivedAt": firestore.SERVER_TIMESTAMP})
    return {"archived": True}
