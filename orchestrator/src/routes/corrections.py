from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from ..dependencies import get_auth_store, AuthStore
from ..pipeline.graph_repair import propose_correction, get_pending_issues

router = APIRouter()


class ProposalRequest(BaseModel):
    action: str
    entity: str
    rationale: str = ""
    proposer: str = "unknown"
    target_b: str | None = None
    proposed_type: str | None = None
    proposed_name: str | None = None


@router.post("/corrections/propose")
def propose(req: ProposalRequest, auth: AuthStore = Depends(get_auth_store)):
    store = auth.store
    try:
        return propose_correction(
            store.conn,
            action=req.action, entity=req.entity, rationale=req.rationale,
            proposer=req.proposer, target_b=req.target_b,
            proposed_type=req.proposed_type, proposed_name=req.proposed_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        store.close()


@router.get("/corrections")
def list_corrections(auth: AuthStore = Depends(get_auth_store)):
    store = auth.store
    try:
        return get_pending_issues(store.conn)
    finally:
        store.close()
