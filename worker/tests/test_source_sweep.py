# ABOUTME: The watched-source scan sweep enqueues scan_source jobs for due sources only.

import json

from src.db import init_db, get_connection
from src.main import enqueue_due_source_scans


def _seed(conn, sid, *, cadence=24, enabled=1, scanned_now=False):
    conn.execute(
        "INSERT INTO watched_sources (id, type, uri, cadence_hours, enabled) VALUES (?, 'vault', '/v', ?, ?)",
        (sid, cadence, enabled))
    if scanned_now:
        conn.execute("UPDATE watched_sources SET last_scanned_at = datetime('now') WHERE id = ?", (sid,))


def _scan_jobs(conn):
    return conn.execute(
        "SELECT target, status, config FROM jobs WHERE type = 'scan_source'").fetchall()


def test_due_source_is_enqueued(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    _seed(conn, "s1")   # last_scanned_at NULL -> due
    conn.commit(); conn.close()

    assert enqueue_due_source_scans([db]) == 1

    conn = get_connection(db)
    jobs = _scan_jobs(conn)
    assert len(jobs) == 1 and jobs[0]["target"] == "s1" and jobs[0]["status"] == "queued"
    assert json.loads(jobs[0]["config"])["source_id"] == "s1"


def test_recently_scanned_source_is_not_due(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    _seed(conn, "s1", cadence=24, scanned_now=True)
    conn.commit(); conn.close()
    assert enqueue_due_source_scans([db]) == 0


def test_disabled_source_is_skipped(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    _seed(conn, "s1", enabled=0)
    conn.commit(); conn.close()
    assert enqueue_due_source_scans([db]) == 0


def test_sweep_is_idempotent_while_a_scan_is_pending(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    _seed(conn, "s1")
    conn.commit(); conn.close()
    assert enqueue_due_source_scans([db]) == 1
    # A scan is now queued; a second sweep must not pile on another.
    assert enqueue_due_source_scans([db]) == 0
