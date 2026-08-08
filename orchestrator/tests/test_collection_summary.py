"""GET /collections/{collection_id}/summary — side-panel payload for a collection node.

Returns the grounded root-level LLM summary (the `code_intent` document linked at
`dc.role == 'root'`) plus top entities by mention count across the collection's
documents.

`role`, not `level`: this schema has no `level` column — it carries the explicit
role/emits_cooccurrence pair that column was split into.
"""


def _seed(store):
    c = store.conn
    # The collection's root summary document (what the ingest job stores at role='root'
    # with content_type='code_intent').
    c.execute("INSERT INTO documents (id, title, content, content_type) "
              "VALUES ('rd', '.', 'This repo does X and Y.', 'code_intent')")
    # File-level docs carrying entity mentions.
    c.execute("INSERT INTO documents (id, title) VALUES ('f1', 'file1')")
    c.execute("INSERT INTO documents (id, title) VALUES ('f2', 'file2')")
    c.execute("INSERT INTO document_domains (document_id, domain_path, is_primary, confidence) "
              "VALUES ('f1', 'alpha', 1, 1.0)")
    c.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'alpha-thing', 'Concept')")
    c.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e2', 'beta-thing', 'Technology')")
    # e1 mentioned in two files, e2 in one → e1 ranks first.
    c.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES ('e1', 'f1')")
    c.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES ('e1', 'f2')")
    c.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES ('e2', 'f1')")

    store.collections.create("r1", "repo-one", "repo-one", "/collections/repo-one")
    store.collections.link_document("rd", "r1", role="root")
    store.collections.link_document("f1", "r1", role="leaf")
    store.collections.link_document("f2", "r1", role="leaf")
    c.commit()


def test_repo_summary_returns_summary_and_top_entities(test_client, test_store):
    _seed(test_store)

    r = test_client.get("/collections/r1/summary")
    assert r.status_code == 200
    body = r.json()

    assert body["collection"]["id"] == "r1"
    assert body["collection"]["name"] == "repo-one"
    assert body["collection"]["domain"] == "alpha"
    assert body["summary"] == "This repo does X and Y."

    ents = body["top_entities"]
    assert [e["name"] for e in ents] == ["alpha-thing", "beta-thing"]  # e1 (2) before e2 (1)
    counts = {e["name"]: e["count"] for e in ents}
    assert counts == {"alpha-thing": 2, "beta-thing": 1}
    assert ents[0]["type"] == "Concept"


def test_repo_summary_respects_limit(test_client, test_store):
    _seed(test_store)
    r = test_client.get("/collections/r1/summary?limit=1")
    assert r.status_code == 200
    assert len(r.json()["top_entities"]) == 1


def test_repo_summary_excludes_invalidated_entities(test_client, test_store):
    _seed(test_store)
    test_store.conn.execute("UPDATE entities SET invalid_at = CURRENT_TIMESTAMP WHERE id = 'e2'")
    test_store.conn.commit()
    r = test_client.get("/collections/r1/summary")
    assert [e["name"] for e in r.json()["top_entities"]] == ["alpha-thing"]


def test_repo_summary_404_for_unknown_repo(test_client):
    r = test_client.get("/collections/does-not-exist/summary")
    assert r.status_code == 404
