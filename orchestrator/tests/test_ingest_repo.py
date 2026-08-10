import json


def test_ingest_repo_enqueues_job(test_client, test_store, tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text("demo repo that does data mining")

    # stub the LLM classification so no Bedrock call happens in the test
    import src.routes.ingest as ingest_mod

    async def fake_classify(*a, **k):
        return {"primary_domain": "development/data-mining", "secondary_domains": [], "confidence": 0.9}

    monkeypatch.setattr(ingest_mod, "classify_document", fake_classify)

    r = test_client.post("/ingest/repo", json={"path": str(tmp_path), "name": "demo"})

    assert r.status_code == 202
    body = r.json()
    assert "job_id" in body and "collection_id" in body

    # a repos row was created for the ingested repo
    row = test_store.conn.execute(
        "SELECT * FROM collections WHERE id = ?", (body["collection_id"],)
    ).fetchone()
    assert row is not None
    assert row["name"] == "demo"

    # a general spec row exists (seeded from orchestrator/specs/general_code.md
    # since none existed before this request)
    spec = test_store.specs.get_general()
    assert spec is not None

    # the queued job carries spec_id + root/repo info. Classification is deferred
    # to the worker (ingest_repo classifies on the grounded repo summary), so the
    # job config does NOT carry a domain_path.
    job = test_store.jobs.get(body["job_id"])
    assert job is not None
    assert job.type == "ingest_repo"
    assert job.target == body["collection_id"]
    assert job.config["spec_id"] == spec.id
    assert "domain_path" not in job.config
    assert job.config["root_path"] == str(tmp_path)
    assert job.config["collection_id"] == body["collection_id"]
    assert job.config["collection_name"] == "demo"


def test_ingest_repo_missing_path_returns_400(test_client, tmp_path):
    missing = tmp_path / "does-not-exist"
    r = test_client.post("/ingest/repo", json={"path": str(missing), "name": "demo"})
    assert r.status_code == 400


def test_ingest_repo_reuses_existing_general_spec(test_client, test_store, tmp_path, monkeypatch):
    """If a general spec already exists, the route must reuse it rather than
    seeding a duplicate."""
    test_store.specs.create("existing-spec-id", None, 1, "existing spec content")

    (tmp_path / "README.md").write_text("demo repo that does data mining")

    import src.routes.ingest as ingest_mod

    async def fake_classify(*a, **k):
        return {"primary_domain": "development/data-mining", "secondary_domains": [], "confidence": 0.9}

    monkeypatch.setattr(ingest_mod, "classify_document", fake_classify)

    r = test_client.post("/ingest/repo", json={"path": str(tmp_path), "name": "demo2"})
    assert r.status_code == 202
    body = r.json()

    job = test_store.jobs.get(body["job_id"])
    assert job.config["spec_id"] == "existing-spec-id"
