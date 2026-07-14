"""#24 pt1 reconciliation: document delete stays correct alongside invalidation.

Deleting a document (hard-delete cascade from #34) must handle an already
soft-deleted (invalid_at) entity cleanly — orphaning it removes it without
error, and no dangling rows remain.
"""


def test_delete_document_cleans_up_invalidated_orphan_entity(test_client, test_store):
    from src.pipeline.graph_repair import apply_invalidation

    c = test_store.conn
    c.execute("INSERT INTO documents (id, title, status) VALUES ('d1', 'Doc', 'extracted')")
    c.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'ghost', 'Concept')")
    c.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES ('e1', 'd1')")
    c.commit()
    # e1 is invalidated but still sourced only by d1.
    apply_invalidation(test_store.conn, "e1", reason="test")

    resp = test_client.delete("/documents/d1")
    assert resp.status_code == 200

    # deleting d1 orphans e1 (its only source) → hard-removed cleanly, nothing dangling
    assert c.execute("SELECT * FROM entities WHERE id = 'e1'").fetchone() is None
    assert c.execute("SELECT * FROM entity_sources WHERE document_id = 'd1'").fetchone() is None
    assert c.execute("SELECT * FROM documents WHERE id = 'd1'").fetchone() is None
