def _seed_entity(test_store):
    conn = test_store.conn
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'panopticon', 'Product')")
    conn.commit()


def test_propose_correction_endpoint_creates_pending(test_client, test_store):
    _seed_entity(test_store)
    resp = test_client.post("/corrections/propose", json={
        "action": "invalidate", "entity": "panopticon",
        "rationale": "metaphor", "proposer": "agent-x",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending" and "issue_id" in body

    listing = test_client.get("/corrections").json()
    assert len(listing) == 1
    assert listing[0]["action"] == "invalidate"
    assert listing[0]["target_entity_name"] == "panopticon"


def test_propose_unknown_entity_is_400(test_client, test_store):
    resp = test_client.post("/corrections/propose", json={
        "action": "invalidate", "entity": "ghost",
    })
    assert resp.status_code == 400


def test_propose_bad_action_is_400(test_client, test_store):
    _seed_entity(test_store)
    resp = test_client.post("/corrections/propose", json={
        "action": "frobnicate", "entity": "panopticon",
    })
    assert resp.status_code == 400


def test_judge_endpoint_enqueues_job(test_client, test_store):
    resp = test_client.post("/corrections/judge")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "queued" and "job_id" in body
    row = test_store.conn.execute(
        "SELECT type, target, status FROM jobs WHERE id = ?", (body["job_id"],)).fetchone()
    assert row[0] == "judge_corrections"
    assert row[2] == "queued"


def test_judge_endpoint_dedupes(test_client, test_store):
    first = test_client.post("/corrections/judge")
    assert first.status_code == 200
    second = test_client.post("/corrections/judge")
    assert second.status_code == 409
