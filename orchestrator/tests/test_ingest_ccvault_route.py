# ABOUTME: /ingest/ccvault route — two-phase like /ingest/repo, but idempotent on ONE
# ABOUTME: persistent per-workspace ccvault collection (agent_report). See docs/ccvault-ingestion.md.


def _archive(tmp_path):
    # The route only checks the path EXISTS (the worker opens the archive). A file suffices.
    p = tmp_path / "ccvault.db"
    p.write_bytes(b"")
    return p


def test_ingest_ccvault_creates_collection_and_enqueues_job(test_client, test_store, tmp_path):
    p = _archive(tmp_path)

    r = test_client.post("/ingest/ccvault", json={"path": str(p)})
    assert r.status_code == 202
    body = r.json()
    assert "job_id" in body and "collection_id" in body

    # one ccvault collection, defaulted to agent_report
    coll = test_store.collections.get_by_path("ccvault")
    assert coll is not None and coll["id"] == body["collection_id"]
    kind = test_store.conn.execute(
        "SELECT kind FROM silo_kind WHERE silo_id = ?", (coll["id"],)).fetchone()[0]
    assert kind == "agent_report"

    # a general spec was seeded and the job carries the wiring
    spec = test_store.specs.get_general()
    assert spec is not None
    job = test_store.jobs.get(body["job_id"])
    assert job.type == "ingest_ccvault"
    assert job.config["archive_path"] == str(p)
    assert job.config["collection_id"] == coll["id"]
    assert job.config["spec_id"] == spec.id


def test_ingest_ccvault_is_idempotent_on_the_collection(test_client, test_store, tmp_path):
    p = _archive(tmp_path)

    first = test_client.post("/ingest/ccvault", json={"path": str(p)}).json()
    second = test_client.post("/ingest/ccvault", json={"path": str(p)}).json()

    # same persistent collection reused (not a new UNIQUE-path row / 409), new job each time
    assert first["collection_id"] == second["collection_id"]
    assert first["job_id"] != second["job_id"]
    n = test_store.conn.execute(
        "SELECT COUNT(*) FROM collections WHERE kind = 'ccvault'").fetchone()[0]
    assert n == 1


def test_ingest_ccvault_custom_label_and_override(test_client, test_store, tmp_path):
    p = _archive(tmp_path)
    r = test_client.post("/ingest/ccvault", json={
        "path": str(p), "label": "sessions-clone-a", "provenance_kind": "human_reviewed"})
    assert r.status_code == 202
    coll = test_store.collections.get_by_path("sessions-clone-a")
    assert coll is not None
    kind = test_store.conn.execute(
        "SELECT kind FROM silo_kind WHERE silo_id = ?", (coll["id"],)).fetchone()[0]
    assert kind == "human_reviewed"   # explicit override wins over the agent_report default


def test_ingest_ccvault_missing_path_returns_400(test_client, tmp_path):
    r = test_client.post("/ingest/ccvault", json={"path": str(tmp_path / "nope.db")})
    assert r.status_code == 400
