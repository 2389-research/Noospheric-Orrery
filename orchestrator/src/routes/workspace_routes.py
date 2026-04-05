"""Workspace CRUD endpoints.

On Firestore: full multi-tenant workspace management.
On SQLite: manages workspaces as separate .db files via a JSON registry.
"""

import os
import json
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import AuthUser, require_role

router = APIRouter()

def _is_sqlite():
    return os.environ.get("DB_BACKEND", "sqlite").lower() == "sqlite"

def _get_firestore_db():
    from google.cloud import firestore
    return firestore.Client()


# --- SQLite workspace registry ---

def _registry_path() -> str:
    from ..config import get_settings
    base_dir = os.path.dirname(get_settings().db_path)
    ws_dir = os.path.join(base_dir, "workspaces")
    os.makedirs(ws_dir, exist_ok=True)
    return os.path.join(ws_dir, "registry.json")

def _load_registry() -> list[dict]:
    path = _registry_path()
    if not os.path.exists(path):
        default = [{"id": "default", "name": "Default", "description": "", "status": "active",
                     "createdAt": datetime.now(timezone.utc).isoformat()}]
        _save_registry(default)
        return default
    with open(path) as f:
        return json.load(f)

def _save_registry(workspaces: list[dict]):
    import tempfile
    path = _registry_path()
    # Atomic write — write to temp file then rename
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(workspaces, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise


# --- Models ---

class CreateWorkspaceRequest(BaseModel):
    name: str
    description: str = ""

class RenameWorkspaceRequest(BaseModel):
    name: str


# --- Endpoints ---

@router.post("/workspaces")
async def create_workspace(
    req: CreateWorkspaceRequest,
    user: AuthUser = Depends(require_role("admin")),
):
    if _is_sqlite():
        ws_id = str(uuid.uuid4())[:8]
        registry = _load_registry()
        registry.append({
            "id": ws_id, "name": req.name, "description": req.description,
            "status": "active", "createdAt": datetime.now(timezone.utc).isoformat(),
        })
        _save_registry(registry)
        return {"workspaceId": ws_id, "name": req.name}

    from google.cloud import firestore
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
    """Return all active workspaces."""
    if _is_sqlite():
        registry = _load_registry()
        return [ws for ws in registry if ws.get("status") != "archived"]

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
    if _is_sqlite():
        registry = _load_registry()
        for ws in registry:
            if ws["id"] == workspace_id:
                ws["name"] = req.name
                _save_registry(registry)
                return {"updated": True}
        raise HTTPException(404, "Workspace not found")

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
    if _is_sqlite():
        registry = _load_registry()
        for ws in registry:
            if ws["id"] == workspace_id:
                ws["status"] = "archived"
                _save_registry(registry)
                return {"archived": True}
        raise HTTPException(404, "Workspace not found")

    from google.cloud import firestore
    db = _get_firestore_db()
    ws_ref = db.collection("workspaces").document(workspace_id)
    ws = ws_ref.get().to_dict()
    if not ws or ws.get("orgId") != user.org_id:
        raise HTTPException(404, "Workspace not found")
    ws_ref.update({"status": "archived", "archivedAt": firestore.SERVER_TIMESTAMP})
    return {"archived": True}
