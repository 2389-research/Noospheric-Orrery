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
        "SELECT id, phase, iteration, scores, composite, key_change, asi, judge_mode, regressed, created_at "
        "FROM simmer_iterations WHERE job_id = ? ORDER BY phase, iteration",
        (job_id,),
    ).fetchall()

    iterations = []
    for r in rows:
        iteration_id = r[0]
        # Get criterion details for this iteration
        details = conn.execute(
            "SELECT criterion, score, seed_score, evidence, improve "
            "FROM simmer_criterion_details WHERE iteration_id = ? ORDER BY criterion",
            (iteration_id,),
        ).fetchall()

        iterations.append({
            "phase": r[1],
            "iteration": r[2],
            "scores": json.loads(r[3]) if r[3] else {},
            "composite": r[4],
            "key_change": r[5],
            "asi": r[6],
            "judge_mode": r[7],
            "regressed": bool(r[8]),
            "created_at": r[9],
            "criterion_details": [
                {"criterion": d[0], "score": d[1], "seed_score": d[2], "evidence": d[3], "improve": d[4]}
                for d in details
            ],
        })
    conn.close()

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
