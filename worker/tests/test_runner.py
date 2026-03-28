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
