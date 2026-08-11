import json


def _make_bundle(tmp_path):
    bundle = tmp_path / "tracker-ingest"
    out_dir, runs_dir = bundle / "out", bundle / "runs"
    out_dir.mkdir(parents=True)
    runs_dir.mkdir(parents=True)
    (out_dir / "index.json").write_text(json.dumps([{"run_label": "run1"}]))
    (out_dir / "run1.json").write_text(json.dumps({"run_label": "run1", "rung": "R0"}))
    return out_dir, runs_dir


def test_ingest_tracker_runs_enqueues_bundle_job(test_client, test_store, tmp_path):
    out_dir, runs_dir = _make_bundle(tmp_path)

    r = test_client.post("/ingest/tracker-runs", json={"path": str(out_dir)})

    assert r.status_code == 202
    body = r.json()
    assert "job_id" in body
    assert body["mode"] == "bundle"  # index.json present -> summaries already exist

    # a general spec row was seeded (none existed before this request)
    spec = test_store.specs.get_general()
    assert spec is not None

    job = test_store.jobs.get(body["job_id"])
    assert job is not None
    assert job.type == "ingest_tracker_runs"
    assert job.config["out_dir"] == str(out_dir)
    assert job.config["raw_root"] is None
    assert job.config["spec_id"] == spec.id
    assert job.config["chain"] is None  # chain order deferred to the worker
    # runs_dir defaults to a sibling of the summaries dir so source_path resolves
    assert job.config["runs_dir"] == str(runs_dir)


def test_a_dir_without_an_index_is_treated_as_a_raw_corpus(test_client, test_store, tmp_path):
    """No index.json -> the worker summarizes the runs itself via orrery-tracksum."""
    corpus = tmp_path / "raw-corpus"
    corpus.mkdir()

    r = test_client.post("/ingest/tracker-runs", json={"path": str(corpus)})
    assert r.status_code == 202
    assert r.json()["mode"] == "raw"

    job = test_store.jobs.get(r.json()["job_id"])
    assert job.config["raw_root"] == str(corpus)
    assert job.config["out_dir"] is None


def test_ingest_tracker_runs_accepts_explicit_chain_and_runs_dir(test_client, test_store, tmp_path):
    out_dir, _ = _make_bundle(tmp_path)
    elsewhere = tmp_path / "staged-elsewhere"
    elsewhere.mkdir()

    r = test_client.post("/ingest/tracker-runs", json={
        "path": str(out_dir),
        "chain": ["run1"],
        "runs_dir": str(elsewhere),
    })
    assert r.status_code == 202

    job = test_store.jobs.get(r.json()["job_id"])
    assert job.config["chain"] == ["run1"]
    assert job.config["runs_dir"] == str(elsewhere)


def test_ingest_tracker_runs_missing_path_returns_400(test_client, tmp_path):
    missing = tmp_path / "does-not-exist"
    r = test_client.post("/ingest/tracker-runs", json={"path": str(missing)})
    assert r.status_code == 400

    afile = tmp_path / "a-file.json"
    afile.write_text("{}")
    r = test_client.post("/ingest/tracker-runs", json={"path": str(afile)})
    assert r.status_code == 400


def test_ingest_tracker_runs_reuses_existing_general_spec(test_client, test_store, tmp_path):
    test_store.specs.create("existing-spec-id", None, 1, "existing spec content")
    out_dir, _ = _make_bundle(tmp_path)

    r = test_client.post("/ingest/tracker-runs", json={"path": str(out_dir)})
    assert r.status_code == 202

    job = test_store.jobs.get(r.json()["job_id"])
    assert job.config["spec_id"] == "existing-spec-id"


def test_a_repeat_bundle_ingest_is_409_even_without_an_explicit_chain(test_client, test_store, tmp_path):
    """The 409 must not depend on the caller supplying `chain`.

    Checking `request.chain` alone meant a repeat ingest WITHOUT a chain sailed past the
    route and failed inside the worker's insert loop — after earlier runs were already
    inserted. That is the partial ingest, with silently incomplete chain_next edges, that
    the guard exists to prevent. In bundle mode the labels are right there in index.json.
    """
    import json

    out = tmp_path / "out"
    out.mkdir()
    (out / "index.json").write_text(json.dumps([
        {"run_label": "runA", "rung": "R5"}, {"run_label": "runB", "rung": "R0"}]))
    for label in ("runA", "runB"):
        (out / f"{label}.json").write_text(json.dumps({"run_label": label, "rollup": "x"}))

    body = {"path": str(out), "runs_dir": str(tmp_path / "runs")}
    assert test_client.post("/ingest/tracker-runs", json=body).status_code == 202

    # A collection now exists for runA, as the worker would have created it.
    test_store.collections.create("c-a", "runA", "runA", str(tmp_path))

    resp = test_client.post("/ingest/tracker-runs", json=body)
    assert resp.status_code == 409, (
        f"expected a conflict from index.json labels, got {resp.status_code}: {resp.text[:200]}")
    assert "runA" in resp.json()["detail"]


def test_an_unreadable_index_does_not_block_the_request(test_client, test_store, tmp_path):
    """index.json is caller-supplied; if it cannot be parsed the WORKER reports it.

    Skipping the early check is not skipping the check — the worker preflights every
    label before writing anything, so a malformed index must not turn into a confusing
    400/409 from the route.
    """
    out = tmp_path / "out"
    out.mkdir()
    (out / "index.json").write_text("{ not valid json")

    resp = test_client.post("/ingest/tracker-runs",
                            json={"path": str(out), "runs_dir": str(tmp_path / "runs")})
    assert resp.status_code == 202
