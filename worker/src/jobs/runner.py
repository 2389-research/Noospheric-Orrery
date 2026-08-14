import json
import sqlite3
from datetime import datetime, timezone

_ORPHAN_RESULT = json.dumps(
    {"error": "orphaned: the worker restarted while this job was 'running'"})


def reset_orphaned_jobs(conn: sqlite3.Connection) -> int:
    """Fail any job left 'running' by a previous worker, and return how many.

    One worker processes jobs serially, so a job still 'running' at startup belongs to
    a process that is gone — it cannot resume. Left alone it stays 'running' forever
    and `/stats active_jobs` never returns to 0, which anything gating on idleness (the
    idle judge included) then reads wrong. Marked 'failed' so the row reaches a terminal
    state; a result the job already wrote (e.g. extract_batch's counts) is preserved via
    COALESCE, because it is real even though completion was never recorded.

    Conservative on purpose: an orphaned 'running' job is indeterminate — it may have
    finished (and only the status write was lost) or died mid-way — and the worker
    cannot tell which, so it does NOT assume success. The extracted data itself is
    already committed regardless; this only settles the job row.
    """
    cur = conn.execute(
        "UPDATE jobs SET status = 'failed', completed_at = ?, "
        "result = COALESCE(result, ?) WHERE status = 'running'",
        (datetime.now(timezone.utc).isoformat(), _ORPHAN_RESULT))
    conn.commit()
    return cur.rowcount


def pick_next_job(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT id, type, target, config FROM jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1").fetchone()
    if not row:
        return None
    return {"id": row[0], "type": row[1], "target": row[2], "config": row[3]}

def mark_job_running(conn: sqlite3.Connection, job_id: str) -> None:
    conn.execute("UPDATE jobs SET status = 'running', started_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), job_id))
    conn.commit()

def mark_job_completed(conn: sqlite3.Connection, job_id: str, result: str | None = None) -> None:
    """Mark a job completed, preserving a result the job wrote itself.

    `result=None` leaves the column alone. Jobs like extract_batch write their own
    outcome JSON mid-run (entity counts, spec version, elapsed time), and the default
    used to be `""` — so the poll loop's completion call overwrote it with an empty
    string the moment the job succeeded, and `GET /jobs` reported nothing for exactly
    the jobs that had the most to report. Pass a string only to set or override it.
    """
    ts = datetime.now(timezone.utc).isoformat()
    if result is None:
        conn.execute("UPDATE jobs SET status = 'completed', completed_at = ? WHERE id = ?",
            (ts, job_id))
    else:
        conn.execute("UPDATE jobs SET status = 'completed', completed_at = ?, result = ? WHERE id = ?",
            (ts, result, job_id))
    conn.commit()

def mark_job_failed(conn: sqlite3.Connection, job_id: str, error: str = "") -> None:
    conn.execute("UPDATE jobs SET status = 'failed', completed_at = ?, result = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), error, job_id))
    conn.commit()
