from fastapi import APIRouter, HTTPException
from ..repositories.factory import get_store

router = APIRouter()

@router.get("/jobs")
def list_jobs(status: str | None = None):
    store = get_store()
    jobs = store.jobs.list(status_filter=status)
    store.close()
    return [
        {
            "id": j.id, "type": j.type, "target": j.target, "status": j.status,
            "created_at": j.created_at, "started_at": j.started_at, "completed_at": j.completed_at,
            "results": j.result,
        }
        for j in jobs
    ]


@router.get("/jobs/{job_id}/iterations")
def get_job_iterations(job_id: str):
    store = get_store()
    result = store.simmer_iterations.get_for_job(job_id)
    if not result:
        store.close()
        raise HTTPException(status_code=404, detail="Job not found")
    store.close()

    job = result["job"]
    phases = result["phases"]
    total = sum(len(iters) for iters in phases.values())

    return {
        "job_id": job_id,
        "job_type": job["type"],
        "target": job["target"],
        "status": job["status"],
        "phases": phases,
        "total_iterations": total,
    }
