import sqlite3
from datetime import datetime, timezone

def pick_next_job(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT id, type, target, config FROM jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1").fetchone()
    if not row:
        return None
    return {"id": row[0], "type": row[1], "target": row[2], "config": row[3]}

def mark_job_running(conn: sqlite3.Connection, job_id: str) -> None:
    conn.execute("UPDATE jobs SET status = 'running', started_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), job_id))
    conn.commit()

def mark_job_completed(conn: sqlite3.Connection, job_id: str, result: str = "") -> None:
    conn.execute("UPDATE jobs SET status = 'completed', completed_at = ?, result = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), result, job_id))
    conn.commit()

def mark_job_failed(conn: sqlite3.Connection, job_id: str, error: str = "") -> None:
    conn.execute("UPDATE jobs SET status = 'failed', completed_at = ?, result = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), error, job_id))
    conn.commit()
