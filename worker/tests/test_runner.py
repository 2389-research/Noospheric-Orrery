from src.db import init_db, get_connection
from src.jobs.runner import pick_next_job, mark_job_running, mark_job_completed, mark_job_failed

def test_pick_next_job_returns_oldest_queued(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES ('j1', 'simmer_general', 'general', 'queued')")
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES ('j2', 'simmer_domain', 'techniques', 'queued')")
    conn.commit()
    job = pick_next_job(conn)
    assert job is not None
    assert job["id"] == "j1"
    conn.close()

def test_pick_next_job_skips_running(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES ('j1', 'simmer_general', 'general', 'running')")
    conn.commit()
    job = pick_next_job(conn)
    assert job is None
    conn.close()

def test_mark_job_running(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES ('j1', 'simmer_general', 'general', 'queued')")
    conn.commit()
    mark_job_running(conn, "j1")
    row = conn.execute("SELECT status, started_at FROM jobs WHERE id = 'j1'").fetchone()
    assert row[0] == "running"
    assert row[1] is not None
    conn.close()

def test_mark_job_completed(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES ('j1', 'simmer_general', 'general', 'running')")
    conn.commit()
    mark_job_completed(conn, "j1", "done")
    row = conn.execute("SELECT status, completed_at, result FROM jobs WHERE id = 'j1'").fetchone()
    assert row[0] == "completed"
    assert row[1] is not None
    assert row[2] == "done"
    conn.close()

def test_completing_a_job_preserves_a_result_the_job_wrote_itself(tmp_path):
    """The poll loop calls mark_job_completed with no result — it must not clobber.

    extract_batch (and repo ingest) write their own outcome JSON mid-run, and then the
    poll loop marks the job complete. With `result=""` as the default that write landed
    on top of theirs, so `GET /jobs` reported an empty result for precisely the jobs
    that had the most to say — and it looked like the job had produced nothing rather
    than like the row had been overwritten.
    """
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES ('j1', 'extract_batch', 'c1', 'running')")
    conn.execute("UPDATE jobs SET result = ? WHERE id = 'j1'", ('{"entities_found": 42}',))
    conn.commit()

    mark_job_completed(conn, "j1")   # exactly how worker/src/main.py calls it

    row = conn.execute("SELECT status, completed_at, result FROM jobs WHERE id = 'j1'").fetchone()
    assert row[0] == "completed"
    assert row[1] is not None
    assert row[2] == '{"entities_found": 42}', "the job's own result was overwritten"
    conn.close()


def test_an_explicit_result_still_overrides(tmp_path):
    """The preserve behaviour is opt-out-able: passing a string still sets it.

    Otherwise a caller could no longer correct or annotate a result, and the fix would
    have traded one silent behaviour for another.
    """
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES ('j1', 'extract_batch', 'c1', 'running')")
    conn.execute("UPDATE jobs SET result = 'stale' WHERE id = 'j1'")
    conn.commit()

    mark_job_completed(conn, "j1", "fresh")

    assert conn.execute("SELECT result FROM jobs WHERE id = 'j1'").fetchone()[0] == "fresh"
    # An empty string is a deliberate value, not "no opinion" — only None means that.
    mark_job_completed(conn, "j1", "")
    assert conn.execute("SELECT result FROM jobs WHERE id = 'j1'").fetchone()[0] == ""
    conn.close()


def test_mark_job_failed(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES ('j1', 'simmer_general', 'general', 'running')")
    conn.commit()
    mark_job_failed(conn, "j1", "some error")
    row = conn.execute("SELECT status, completed_at, result FROM jobs WHERE id = 'j1'").fetchone()
    assert row[0] == "failed"
    assert row[1] is not None
    assert row[2] == "some error"
    conn.close()
