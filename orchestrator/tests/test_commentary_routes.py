import json


def _insert(store, node_type, node_id, comments):
    store.conn.execute(
        "INSERT OR REPLACE INTO node_commentary "
        "(node_type, node_id, comments_json, model, source_hash) VALUES (?,?,?,?,?)",
        (node_type, node_id, json.dumps(comments), "gemma4:e4b", "hash"))
    store.conn.commit()


SAMPLE = [
    {"kind": "description", "text": "A thing.", "pose": "reading"},
    {"kind": "omnissiah", "text": "It matters.", "pose": "galxy"},
    {"kind": "humor", "text": "Amusing.", "pose": "pointing"},
]


def test_get_commentary_404_when_absent(test_client):
    r = test_client.get("/commentary/collection/does-not-exist")
    assert r.status_code == 404


def test_get_commentary_returns_payload(test_client, test_store):
    _insert(test_store, "collection", "repo-1", SAMPLE)
    r = test_client.get("/commentary/collection/repo-1")
    assert r.status_code == 200
    body = r.json()
    assert body["node_type"] == "collection" and body["node_id"] == "repo-1"
    assert body["model"] == "gemma4:e4b"
    assert [c["kind"] for c in body["comments"]] == ["description", "omnissiah", "humor"]
    assert body["comments"][2]["pose"] == "pointing"


def test_get_commentary_rejects_entity_type(test_client):
    # entity is out of the v1 public contract → 400, not 404
    assert test_client.get("/commentary/entity/anything").status_code == 400


def test_get_commentary_domain_path_with_slashes(test_client, test_store):
    # domain node_id is a slash-containing path — the :path converter must handle it
    _insert(test_store, "domain", "software/developer-tools/dsl-compiler", SAMPLE)
    r = test_client.get("/commentary/domain/software/developer-tools/dsl-compiler")
    assert r.status_code == 200
    assert r.json()["node_id"] == "software/developer-tools/dsl-compiler"


def test_get_commentary_rejects_unknown_type(test_client):
    r = test_client.get("/commentary/planet/xyz")
    assert r.status_code == 400


def test_backfill_enqueues_job(test_client, test_store):
    r = test_client.post("/commentary/backfill", json={"node_types": ["collection"], "limit": 5})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    job = test_store.jobs.get(job_id)
    assert job is not None
    assert job.type == "generate_commentary"
    assert job.status == "queued"
    assert job.config["node_types"] == ["collection"] and job.config["limit"] == 5


def test_backfill_defaults_and_bad_type(test_client):
    ok = test_client.post("/commentary/backfill", json={})
    assert ok.status_code == 200
    assert ok.json()["config"]["only_missing"] is True
    bad = test_client.post("/commentary/backfill", json={"node_types": ["collection", "galaxy"]})
    assert bad.status_code == 400
