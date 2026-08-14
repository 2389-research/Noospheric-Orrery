def _soft_delete(store, doc_id):
    store.conn.execute("UPDATE documents SET invalid_at = CURRENT_TIMESTAMP WHERE id = ?", (doc_id,))
    store.conn.commit()


def test_soft_deleted_document_hidden_from_repo_reads(test_store):
    store = test_store
    store.documents.create("keep", "Keep", "body one", "h1", "/a.md")
    store.documents.create("gone", "Gone", "body two", "h2", "/b.md")
    _soft_delete(store, "gone")

    assert store.documents.count() == 1
    assert store.documents.get("gone") is None
    assert store.documents.get("keep") is not None
    listed = {d.id for d in store.documents.list(limit=100, offset=0)}
    assert "gone" not in listed and "keep" in listed
    recent = {d.id for d in store.documents.get_recent(100)}
    assert "gone" not in recent and "keep" in recent


def test_soft_deleted_document_hidden_from_routes(test_client, test_store):
    store = test_store
    store.documents.create("keep", "Keep", "body one", "h1", "/a.md")
    store.documents.create("gone", "Gone", "body two", "h2", "/b.md")
    _soft_delete(store, "gone")

    listing = test_client.get("/documents").json()
    ids = {d["id"] for d in listing}
    assert "gone" not in ids and "keep" in ids

    assert test_client.get("/documents/gone").status_code == 404
    assert test_client.get("/documents/keep").status_code == 200
