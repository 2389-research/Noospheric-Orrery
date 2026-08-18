# ABOUTME: GET /jobs/{id} + progress surfacing for the extraction detail-page bar (#51).
import json


def _seed_progress(store, job_id, progress):
    store.conn.execute("UPDATE jobs SET progress = ? WHERE id = ?",
                       (json.dumps(progress), job_id))
    store.conn.commit()


def test_get_job_returns_progress(test_store, test_client):
    test_store.jobs.create("job1", "extract_batch", "all", {"scope": "all"})
    _seed_progress(test_store, "job1", {"docs_done": 3, "docs_total": 10, "entities_so_far": 42})

    r = test_client.get("/jobs/job1")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "job1"
    assert body["progress"] == {"docs_done": 3, "docs_total": 10, "entities_so_far": 42}


def test_get_job_404_for_unknown(test_client):
    assert test_client.get("/jobs/does-not-exist").status_code == 404


def test_list_jobs_includes_progress(test_store, test_client):
    test_store.jobs.create("job2", "extract_batch", "all", {})
    _seed_progress(test_store, "job2", {"docs_done": 1, "docs_total": 2, "entities_so_far": 5})

    r = test_client.get("/jobs")
    assert r.status_code == 200
    job = next(j for j in r.json() if j["id"] == "job2")
    assert job["progress"]["docs_total"] == 2


def test_progress_absent_is_null(test_store, test_client):
    test_store.jobs.create("job3", "extract_batch", "all", {})
    r = test_client.get("/jobs/job3")
    assert r.status_code == 200
    assert r.json()["progress"] is None
