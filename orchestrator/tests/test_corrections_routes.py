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
