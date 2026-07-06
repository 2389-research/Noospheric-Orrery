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


def test_invalidated_entity_hidden_from_reads(test_client, test_store):
    conn = test_store.conn
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1','ghostnode','Product')")
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e2','realnode','Product')")
    conn.execute("INSERT INTO relationships (id, from_entity, to_entity, type, weight) VALUES ('r1','e1','e2','co_occurs',2)")
    conn.commit()
    # propose + approve invalidate on ghostnode
    pid = test_client.post("/corrections/propose", json={"action":"invalidate","entity":"ghostnode"}).json()["issue_id"]
    assert test_client.post(f"/corrections/review/{pid}?action=approve").status_code == 200
    names = [e["canonical_name"] for e in test_client.get("/entities").json()]
    assert "ghostnode" not in names and "realnode" in names


def test_invalidated_entity_still_found_for_dedup(test_client, test_store):
    conn = test_store.conn
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1','ghostnode','Product')")
    conn.commit()
    pid = test_client.post("/corrections/propose", json={"action":"invalidate","entity":"ghostnode"}).json()["issue_id"]
    assert test_client.post(f"/corrections/review/{pid}?action=approve").status_code == 200
    # display path (GET /entities → list) hides the invalidated node
    names = [e["canonical_name"] for e in test_client.get("/entities").json()]
    assert "ghostnode" not in names
    # dedup/write path still finds it → re-ingest re-attaches instead of duplicating (resurrecting)
    assert test_store.entities.get_by_name("ghostnode", "Product", include_invalid=True) is not None
    assert test_store.entities.get_by_name("ghostnode", "Product") is None


def test_resolve_route_reject_and_approve(test_client, test_store):
    conn = test_store.conn
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1','panopticon','Product')")
    conn.commit()
    pid = test_client.post("/corrections/propose", json={"action":"invalidate","entity":"panopticon"}).json()["issue_id"]
    r = test_client.post(f"/corrections/review/{pid}?action=reject")
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    # resolved issue leaves the pending queue
    assert all(c["id"] != pid for c in test_client.get("/corrections").json())


def test_resolve_route_bad_action_400(test_client, test_store):
    assert test_client.post("/corrections/review/nope?action=frob").status_code == 400


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
