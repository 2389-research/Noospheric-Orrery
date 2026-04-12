"""Tests for image pipeline: content_type migration, image_prep, domain counts, image serving."""

import sqlite3
from pathlib import Path
from src.db import init_db, get_connection
from src.repositories.sqlite_store import SQLiteDataStore


def test_init_db_adds_content_type_column(tmp_path):
    """content_type and thumbnail_path columns exist after init."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)").fetchall()}
    conn.close()
    assert "content_type" in cols
    assert "thumbnail_path" in cols


def test_content_type_migration_on_existing_db(tmp_path):
    """init_db adds content_type column to a DB that doesn't have it."""
    db_path = str(tmp_path / "test.db")
    # Create DB without content_type (simulating old schema)
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE documents (
        id TEXT PRIMARY KEY, title TEXT, source_path TEXT,
        content TEXT, content_hash TEXT, metadata TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'pending'
    )""")
    conn.execute("INSERT INTO documents (id, title) VALUES ('doc1', 'test.jpg')")
    conn.commit()
    conn.close()

    # init_db should add the columns
    init_db(db_path)
    conn = get_connection(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)").fetchall()}
    assert "content_type" in cols
    assert "thumbnail_path" in cols
    # Existing row should have default
    row = conn.execute("SELECT content_type FROM documents WHERE id = 'doc1'").fetchone()
    assert row[0] == "text"
    conn.close()


def test_document_create_with_content_type(test_store):
    """documents.create() stores content_type correctly."""
    test_store.documents.create("img1", "photo.jpg", "description", "hash1", "/path/photo.jpg", content_type="image")
    test_store.documents.create("txt1", "notes.md", "some text", "hash2", "/path/notes.md")

    img = test_store.documents.get("img1")
    txt = test_store.documents.get("txt1")
    assert img.content_type == "image"
    assert txt.content_type == "text"


def test_document_list_includes_content_type(test_store):
    """documents.list() returns content_type on each document."""
    test_store.documents.create("img1", "photo.jpg", "desc", "hash1", content_type="image")
    test_store.documents.create("txt1", "notes.md", "text", "hash2", content_type="text")

    docs = test_store.documents.list()
    types = {d.title: d.content_type for d in docs}
    assert types["photo.jpg"] == "image"
    assert types["notes.md"] == "text"


def test_get_recent_includes_content_type(test_store):
    """documents.get_recent() returns content_type."""
    test_store.documents.create("img1", "photo.jpg", "desc", "hash1", content_type="image")
    docs = test_store.documents.get_recent()
    assert docs[0].content_type == "image"


def test_star_graph_includes_content_type(test_store):
    """star-graph documents include content_type."""
    # Set up: document, entity, entity_source
    test_store.documents.create("img1", "photo.jpg", "desc", "hash1", content_type="image")
    test_store.conn.execute(
        "INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'test entity', 'Thing')"
    )
    test_store.conn.execute(
        "INSERT INTO entity_sources (entity_id, document_id, extraction_pass) VALUES ('e1', 'img1', 'general')"
    )
    test_store.conn.commit()

    result = test_store.relationships.get_star_graph("e1")
    assert result is not None
    assert len(result["documents"]) == 1
    assert result["documents"][0]["content_type"] == "image"


class TestImagePrep:
    """Tests for pipeline/image_prep.py"""

    def test_is_image_file(self):
        from src.pipeline.image_prep import is_image_file
        assert is_image_file("photo.jpg")
        assert is_image_file("photo.JPEG")
        assert is_image_file("image.png")
        assert is_image_file("pic.webp")
        assert is_image_file("anim.gif")
        assert not is_image_file("notes.md")
        assert not is_image_file("data.json")
        assert not is_image_file("file.txt")

    def test_is_image_file_with_path(self):
        from src.pipeline.image_prep import is_image_file
        assert is_image_file("/path/to/photo.jpg")
        assert not is_image_file("/path/to/notes.md")


class TestDomainCounts:
    """Tests for per-domain text/image counts in the domains route."""

    def test_domain_counts_endpoint(self, test_client, test_store):
        # Create docs with different content types
        test_store.documents.create("txt1", "notes.md", "text", "h1", content_type="text")
        test_store.documents.create("img1", "photo.jpg", "desc", "h2", content_type="image")
        test_store.documents.create("img2", "photo2.jpg", "desc2", "h3", content_type="image")

        # Create domain and assign docs
        test_store.conn.execute(
            "INSERT INTO domains (id, path, document_count) VALUES ('d1', 'test/domain', 3)"
        )
        for doc_id in ["txt1", "img1", "img2"]:
            test_store.conn.execute(
                "INSERT INTO document_domains (document_id, domain_path, is_primary, confidence) VALUES (?, 'test/domain', 1, 1.0)",
                (doc_id,)
            )
        test_store.conn.commit()

        resp = test_client.get("/domains")
        assert resp.status_code == 200
        domains = resp.json()
        d = next(d for d in domains if d["path"] == "test/domain")
        assert d["text_count"] == 1
        assert d["image_count"] == 2
        assert d["document_count"] == 3
