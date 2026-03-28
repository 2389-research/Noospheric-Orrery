import json
from fastapi import APIRouter, HTTPException
from ..config import get_settings
from ..db import get_connection

router = APIRouter()

@router.get("/jobs")
def list_jobs(status: str | None = None):
    settings = get_settings()
    conn = get_connection(settings.db_path)
    if status:
        rows = conn.execute("SELECT id, type, target, status, created_at, started_at, completed_at FROM jobs WHERE status = ? ORDER BY created_at DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT id, type, target, status, created_at, started_at, completed_at FROM jobs ORDER BY created_at DESC").fetchall()
    conn.close()
    return [{"id": r[0], "type": r[1], "target": r[2], "status": r[3], "created_at": r[4], "started_at": r[5], "completed_at": r[6]} for r in rows]


@router.get("/jobs/{job_id}/iterations")
def get_job_iterations(job_id: str):
    """Get simmer iteration history for a job."""
    settings = get_settings()
    conn = get_connection(settings.db_path)

    job = conn.execute("SELECT id, type, target, status FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        conn.close()
        raise HTTPException(status_code=404, detail="Job not found")

    rows = conn.execute(
        "SELECT phase, iteration, scores, composite, key_change, asi, judge_mode, regressed, created_at "
        "FROM simmer_iterations WHERE job_id = ? ORDER BY phase, iteration",
        (job_id,),
    ).fetchall()
    conn.close()

    iterations = []
    for r in rows:
        iterations.append({
            "phase": r[0],
            "iteration": r[1],
            "scores": json.loads(r[2]) if r[2] else {},
            "composite": r[3],
            "key_change": r[4],
            "asi": r[5],
            "judge_mode": r[6],
            "regressed": bool(r[7]),
            "created_at": r[8],
        })

    # Group by phase
    phases = {}
    for it in iterations:
        phases.setdefault(it["phase"], []).append(it)

    return {
        "job_id": job_id,
        "job_type": job[1],
        "target": job[2],
        "status": job[3],
        "phases": phases,
        "total_iterations": len(iterations),
    }
