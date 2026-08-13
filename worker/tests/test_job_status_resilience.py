# ABOUTME: A finished job's outcome must survive a locked DB — retried, then reconciled.
# ABOUTME: The old path lost a completion write into a generic handler; the row stuck 'running'.
"""A job that did its work must not be recorded as if it never ran.

The failure this covers happened live: extract_batch finished (26 docs, 135 entities
committed), then the completion write hit `database is locked`, the fallback failure
write hit it too, and the exception fell through to the generic poll handler. The row
stayed `running` forever and `active_jobs` never returned to 0. Two defences:

1. the terminal-state write is retried on a locked DB and, if it truly can't be written,
   announced rather than swallowed;
2. any job left `running` at worker startup is reconciled to a terminal state, so a lost
   write can't strand a row across a restart.
"""
import json
import uuid

from src.db import get_connection, init_db
from src.jobs.runner import reset_orphaned_jobs


def _job(conn, status, result=None):
    jid = str(uuid.uuid4())
    conn.execute("INSERT INTO jobs (id, type, target, status, result) VALUES (?, 'extract_batch', 't', ?, ?)",
                 (jid, status, result))
    conn.commit()
    return jid


def test_reconciler_fails_a_running_job_and_leaves_others(tmp_path):
    db_path = str(tmp_path / "t.db")
    init_db(db_path)
    conn = get_connection(db_path)
    running = _job(conn, "running")
    queued = _job(conn, "queued")
    completed = _job(conn, "completed")

    assert reset_orphaned_jobs(conn) == 1, "reconciled the wrong number of jobs"

    status = {r[0]: r[1] for r in conn.execute("SELECT id, status FROM jobs")}
    conn.close()
    assert status[running] == "failed", "the orphaned running job was not settled"
    assert status[queued] == "queued", "a queued job was touched"
    assert status[completed] == "completed", "a completed job was touched"


def test_reconciler_preserves_a_result_the_job_already_wrote(tmp_path):
    """The live case: extract_batch wrote its counts, then failed to record completion.
    Marking it failed must not erase the counts it really produced."""
    db_path = str(tmp_path / "t.db")
    init_db(db_path)
    conn = get_connection(db_path)
    real = json.dumps({"entities_new": 135, "docs_processed": 26})
    jid = _job(conn, "running", result=real)

    reset_orphaned_jobs(conn)

    row = conn.execute("SELECT status, result FROM jobs WHERE id = ?", (jid,)).fetchone()
    conn.close()
    assert row[0] == "failed"
    assert json.loads(row[1])["entities_new"] == 135, "the job's real result was overwritten"


def test_reconciler_fills_a_reason_when_there_was_no_result(tmp_path):
    db_path = str(tmp_path / "t.db")
    init_db(db_path)
    conn = get_connection(db_path)
    jid = _job(conn, "running", result=None)

    reset_orphaned_jobs(conn)

    result = conn.execute("SELECT result FROM jobs WHERE id = ?", (jid,)).fetchone()[0]
    conn.close()
    assert "orphaned" in json.loads(result)["error"]


def test_record_terminal_state_writes_completion_normally(tmp_path):
    import src.main as m
    db_path = str(tmp_path / "t.db")
    init_db(db_path)
    conn = get_connection(db_path)
    jid = _job(conn, "running")
    conn.close()

    assert m._record_terminal_state(db_path, jid, completed=True) is True

    conn = get_connection(db_path)
    status = conn.execute("SELECT status FROM jobs WHERE id = ?", (jid,)).fetchone()[0]
    conn.close()
    assert status == "completed"


def test_record_terminal_state_gives_up_cleanly_when_the_db_stays_locked(tmp_path, monkeypatch):
    """It must NOT raise into the poll loop, and must leave the row 'running' for the
    reconciler — not half-written, not silently dropped."""
    import src.main as m
    db_path = str(tmp_path / "t.db")
    init_db(db_path)
    conn = get_connection(db_path)
    jid = _job(conn, "running")
    conn.close()

    # A peer holds the write lock for the duration.
    holder = get_connection(db_path)
    holder.execute("BEGIN IMMEDIATE")
    holder.execute("UPDATE jobs SET target = 'held'")

    # Make the recorder fail fast instead of waiting out the real 30s busy_timeout.
    real = m.get_connection
    def _short(path):
        c = real(path)
        c.execute("PRAGMA busy_timeout=50")
        return c
    monkeypatch.setattr(m, "get_connection", _short)

    ok = m._record_terminal_state(db_path, jid, completed=True, attempts=2)
    holder.rollback()
    holder.close()

    assert ok is False, "claimed success while the DB was locked"
    conn = get_connection(db_path)
    status = conn.execute("SELECT status FROM jobs WHERE id = ?", (jid,)).fetchone()[0]
    conn.close()
    assert status == "running", "left the row in a non-'running' state the reconciler won't catch"
