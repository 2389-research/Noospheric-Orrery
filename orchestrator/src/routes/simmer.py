import uuid
import json
from fastapi import APIRouter, HTTPException
from ..config import get_settings
from ..db import get_connection

router = APIRouter()

@router.post("/simmer/general")
def trigger_general_simmer():
    settings = get_settings()
    conn = get_connection(settings.db_path)
    existing = conn.execute("SELECT id FROM jobs WHERE type = 'simmer_general' AND status IN ('queued', 'running')").fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=409, detail="General simmer already in progress")
    job_id = str(uuid.uuid4())
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES (?, 'simmer_general', 'general', 'queued')", (job_id,))
    conn.commit()
    conn.close()
    return {"job_id": job_id, "status": "queued"}

@router.post("/simmer/{domain_path:path}")
def trigger_domain_simmer(domain_path: str):
    settings = get_settings()
    conn = get_connection(settings.db_path)
    domain = conn.execute("SELECT path FROM domains WHERE path = ?", (domain_path,)).fetchone()
    if not domain:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Domain not found: {domain_path}")
    existing = conn.execute("SELECT id FROM jobs WHERE type = 'simmer_domain' AND target = ? AND status IN ('queued', 'running')", (domain_path,)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=409, detail=f"Domain simmer already in progress for {domain_path}")
    job_id = str(uuid.uuid4())
    conn.execute("INSERT INTO jobs (id, type, target, status, config) VALUES (?, 'simmer_domain', ?, 'queued', ?)",
        (job_id, domain_path, json.dumps({"domain": domain_path})))
    conn.commit()
    conn.close()
    return {"job_id": job_id, "status": "queued"}
