"""Tests for DELETE /documents/{id} and GET /documents/{id}/file."""


def test_delete_removes_document_and_entity_sources(test_client, test_store):
    conn = test_store.conn
    conn.execute("INSERT INTO documents (id, title, status) VALUES ('d1', 'Doc', 'extracted')")
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'Alice', 'Person')")
    conn.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES ('e1', 'd1')")
    conn.commit()

    resp = test_client.delete("/documents/d1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["deleted"] is True

    assert conn.execute("SELECT * FROM documents WHERE id = 'd1'").fetchone() is None
    assert conn.execute("SELECT * FROM entity_sources WHERE document_id = 'd1'").fetchone() is None


def test_entity_with_remaining_sources_survives(test_client, test_store):
    conn = test_store.conn
    conn.execute("INSERT INTO documents (id, title, status) VALUES ('d1', 'Doc1', 'extracted')")
    conn.execute("INSERT INTO documents (id, title, status) VALUES ('d2', 'Doc2', 'extracted')")
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'Alice', 'Person')")
    conn.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES ('e1', 'd1')")
    conn.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES ('e1', 'd2')")
    conn.commit()

    resp = test_client.delete("/documents/d1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["entities_removed"] == []

    # entity survives because it still has a source on d2
    assert conn.execute("SELECT * FROM entities WHERE id = 'e1'").fetchone() is not None
    assert conn.execute("SELECT * FROM entity_sources WHERE document_id = 'd2'").fetchone() is not None


def test_entity_with_zero_remaining_sources_is_removed(test_client, test_store):
    conn = test_store.conn
    conn.execute("INSERT INTO documents (id, title, status) VALUES ('d1', 'Doc1', 'extracted')")
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'Alice', 'Person')")
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e2', 'Bob', 'Person')")
    conn.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES ('e1', 'd1')")
    conn.execute("INSERT INTO entity_embeddings (entity_id, embedding) VALUES ('e1', NULL)")
    conn.execute("INSERT INTO merge_map (from_name, to_entity_id) VALUES ('Al', 'e1')")
    conn.execute(
        "INSERT INTO relationships (id, from_entity, to_entity, type, weight) VALUES ('r1', 'e1', 'e2', 'co_occurs', 1.0)"
    )
    conn.commit()

    resp = test_client.delete("/documents/d1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["entities_removed"] == ["e1"]

    assert conn.execute("SELECT * FROM entities WHERE id = 'e1'").fetchone() is None
    assert conn.execute("SELECT * FROM entity_embeddings WHERE entity_id = 'e1'").fetchone() is None
    assert conn.execute("SELECT * FROM merge_map WHERE to_entity_id = 'e1'").fetchone() is None
    assert conn.execute("SELECT * FROM relationships WHERE id = 'r1'").fetchone() is None
    # unrelated entity untouched
    assert conn.execute("SELECT * FROM entities WHERE id = 'e2'").fetchone() is not None


def test_domain_document_count_decrements(test_client, test_store):
    conn = test_store.conn
    conn.execute("INSERT INTO documents (id, title, status) VALUES ('d1', 'Doc1', 'extracted')")
    conn.execute("INSERT INTO domains (id, path, document_count) VALUES ('dm1', 'test/domain', 3)")
    conn.execute(
        "INSERT INTO document_domains (document_id, domain_path, is_primary, confidence) VALUES ('d1', 'test/domain', 1, 0.9)"
    )
    conn.commit()

    resp = test_client.delete("/documents/d1")
    assert resp.status_code == 200

    row = conn.execute("SELECT document_count FROM domains WHERE path = 'test/domain'").fetchone()
    assert row["document_count"] == 2

    assert conn.execute("SELECT * FROM document_domains WHERE document_id = 'd1'").fetchone() is None


def test_domain_document_count_floors_at_zero(test_client, test_store):
    conn = test_store.conn
    conn.execute("INSERT INTO documents (id, title, status) VALUES ('d1', 'Doc1', 'extracted')")
    conn.execute("INSERT INTO domains (id, path, document_count) VALUES ('dm1', 'test/domain', 0)")
    conn.execute(
        "INSERT INTO document_domains (document_id, domain_path, is_primary, confidence) VALUES ('d1', 'test/domain', 1, 0.9)"
    )
    conn.commit()

    resp = test_client.delete("/documents/d1")
    assert resp.status_code == 200

    row = conn.execute("SELECT document_count FROM domains WHERE path = 'test/domain'").fetchone()
    assert row["document_count"] == 0


def test_delete_404_on_missing_id(test_client, test_store):
    resp = test_client.delete("/documents/nonexistent")
    assert resp.status_code == 404


def test_delete_removes_chunks(test_client, test_store):
    conn = test_store.conn
    conn.execute("INSERT INTO documents (id, title, status) VALUES ('d1', 'Doc1', 'extracted')")
    conn.execute(
        "INSERT INTO chunks (id, document_id, chunk_index, offset, length, text) VALUES ('c1', 'd1', 0, 0, 5, 'hello')"
    )
    conn.commit()

    resp = test_client.delete("/documents/d1")
    assert resp.status_code == 200
    assert conn.execute("SELECT * FROM chunks WHERE document_id = 'd1'").fetchone() is None


# ---------------------------------------------------------------------------
# GET /documents/{id}/file
# ---------------------------------------------------------------------------

def test_serve_file_not_found(test_client, test_store):
    resp = test_client.get("/documents/nonexistent/file")
    assert resp.status_code == 404


def test_serve_file_text_served_raw(test_client, test_store, tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("hello world")
    test_store.documents.create("d1", "notes.md", "hello world", "hash1", source_path=str(source))

    resp = test_client.get("/documents/d1/file")
    assert resp.status_code == 200
    assert resp.text == "hello world"
    assert "text/plain" in resp.headers["content-type"]


def test_serve_file_pdf_served_as_content_text(test_client, test_store):
    test_store.documents.create(
        "d1", "report.pdf", "Extracted PDF text content", "hash1", source_path="/nonexistent/report.pdf"
    )

    resp = test_client.get("/documents/d1/file")
    assert resp.status_code == 200
    assert resp.text == "Extracted PDF text content"
    assert "text/plain" in resp.headers["content-type"]


def test_serve_file_docx_served_as_content_text(test_client, test_store):
    test_store.documents.create(
        "d1", "report.docx", "Extracted DOCX text content", "hash1", source_path="/nonexistent/report.docx"
    )

    resp = test_client.get("/documents/d1/file")
    assert resp.status_code == 200
    assert resp.text == "Extracted DOCX text content"


def test_serve_file_missing_text_file_on_disk(test_client, test_store):
    test_store.documents.create(
        "d1", "notes.md", "hello", "hash1", source_path="/nonexistent/notes.md"
    )
    resp = test_client.get("/documents/d1/file")
    assert resp.status_code == 404
