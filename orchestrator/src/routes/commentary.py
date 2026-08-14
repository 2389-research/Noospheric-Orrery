import json
import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from ..dependencies import get_auth_store, AuthStore

router = APIRouter()

# Public v1 contract is domains + repos only. Entities are deferred (long tail);
# the worker retains internal capability if a future version re-enables them here.
_NODE_TYPES = {"domain", "collection"}


class BackfillRequest(BaseModel):
    node_types: Optional[list[str]] = None                 # subset of {domain,collection}; None → both
    limit: int = Field(default=50, ge=1, le=2000)          # max nodes per type to generate (bounded — see design §3.4)
    only_missing: bool = True                              # skip nodes that already have commentary
    model: Optional[str] = None                            # None → worker's extraction_model


@router.post("/commentary/backfill")
def backfill_commentary(req: BackfillRequest, auth: AuthStore = Depends(get_auth_store)):
    """Enqueue a generate_commentary job for this noosphere.

    Lands the job in the DB of the noosphere the request targets; the worker's
    workspace scan drains it against that same DB (no explicit DB selection)."""
    store = auth.store
    try:
        if req.node_types is not None:
            bad = [t for t in req.node_types if t not in _NODE_TYPES]
            if bad:
                raise HTTPException(status_code=400, detail=f"Unknown node_types: {bad}")
        job_id = str(uuid.uuid4())
        config = {
            "node_types": req.node_types,
            "limit": req.limit,
            "only_missing": req.only_missing,
            "model": req.model,
        }
        store.jobs.create(job_id, "generate_commentary", "commentary", config=config)
    finally:
        store.close()
    return {"job_id": job_id, "status": "queued", "config": config}


@router.get("/commentary/{node_type}/{node_id:path}")
def get_commentary(node_type: str, node_id: str, auth: AuthStore = Depends(get_auth_store)):
    """Return the pre-generated Magos Lex commentary for a node, or 404 if none.

    The :path converter is required because a domain's node_id is its domains.path
    and contains '/'. Callers URL-encode the id."""
    store = auth.store
    try:
        if node_type not in _NODE_TYPES:
            raise HTTPException(status_code=400, detail=f"Unknown node_type: {node_type}")
        row = store.conn.execute(
            "SELECT comments_json, model FROM node_commentary WHERE node_type=? AND node_id=?",
            (node_type, node_id),
        ).fetchone()
    finally:
        store.close()
    if not row:
        raise HTTPException(status_code=404, detail="No commentary for this node")
    return {"node_type": node_type, "node_id": node_id,
            "model": row["model"], "comments": json.loads(row["comments_json"])}
