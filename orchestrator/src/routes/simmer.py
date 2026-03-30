import uuid
from fastapi import APIRouter, HTTPException
from ..dependencies import get_auth_store, AuthStore
from ..repositories.factory import get_store

router = APIRouter()

@router.post("/simmer/general")
def trigger_general_simmer():
    store = get_store()
    existing = store.jobs.get_existing("simmer_general", "general", ["queued", "running"])
    if existing:
        store.close()
        raise HTTPException(status_code=409, detail="General simmer already in progress")
    job_id = str(uuid.uuid4())
    store.jobs.create(job_id, "simmer_general", "general")
    store.close()
    return {"job_id": job_id, "status": "queued"}

@router.post("/simmer/{domain_path:path}")
def trigger_domain_simmer(domain_path: str):
    store = get_store()
    domain = store.domains.get(domain_path)
    if not domain:
        store.close()
        raise HTTPException(status_code=404, detail=f"Domain not found: {domain_path}")
    existing = store.jobs.get_existing("simmer_domain", domain_path, ["queued", "running"])
    if existing:
        store.close()
        raise HTTPException(status_code=409, detail=f"Domain simmer already in progress for {domain_path}")
    job_id = str(uuid.uuid4())
    store.jobs.create(job_id, "simmer_domain", domain_path, config={"domain": domain_path})
    store.close()
    return {"job_id": job_id, "status": "queued"}
