import sqlite3
import tempfile
import os
from src.db import init_db, get_connection

def test_init_db_creates_tables(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()
    assert "documents" in tables
    assert "chunks" in tables
    assert "domains" in tables
    assert "entities" in tables
    assert "entity_sources" in tables
    assert "merge_map" in tables
    assert "relationships" in tables
    assert "jobs" in tables
    assert "specs" in tables
    assert "document_domains" in tables
    assert "domain_merge_map" in tables

def test_init_db_enables_wal(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.execute("PRAGMA journal_mode")
    mode = cursor.fetchone()[0]
    conn.close()
    assert mode == "wal"

def test_init_db_idempotent(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    init_db(db_path)  # Should not raise
    conn = get_connection(db_path)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()
    assert "documents" in tables


def test_document_image_columns(tmp_path):
    """Documents table has content_type, image_path, thumbnail_path for image support."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO documents (id, title, content, status, content_type, image_path, thumbnail_path) "
        "VALUES ('d1', 'photo', '', 'pending', 'image', '/data/img.jpg', '/data/thumb.jpg')"
    )
    row = conn.execute("SELECT content_type, image_path, thumbnail_path FROM documents WHERE id = 'd1'").fetchone()
    assert row["content_type"] == "image"
    assert row["image_path"] == "/data/img.jpg"
    assert row["thumbnail_path"] == "/data/thumb.jpg"
    # Default is 'text'
    conn.execute("INSERT INTO documents (id, title, content, status) VALUES ('d2', 'notes', 'hello', 'pending')")
    row2 = conn.execute("SELECT content_type FROM documents WHERE id = 'd2'").fetchone()
    assert row2["content_type"] == "text"
    conn.close()


def test_chunk_image_embedding_column(tmp_path):
    """Chunks table has image_embedding BLOB for SigLIP embeddings."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO documents (id, title, content, status) VALUES ('d1', 'test', '', 'pending')"
    )
    conn.execute(
        "INSERT INTO chunks (id, document_id, chunk_index, text, image_embedding) "
        "VALUES ('c1', 'd1', 0, '', X'0102030405')"
    )
    row = conn.execute("SELECT image_embedding FROM chunks WHERE id = 'c1'").fetchone()
    assert row["image_embedding"] is not None
    conn.close()


def test_chunks_table_has_section_column(tmp_path):
    from src.db import init_db
    import sqlite3
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(chunks)").fetchall()}
    assert "section" in cols
    conn.close()


def test_chunk_repository_round_trips_section(tmp_path):
    from src.db import init_db, get_connection
    from src.repositories.sqlite_store import SQLiteChunkRepository, SQLiteDocumentRepository
    from src.repositories.interfaces import Chunk
    import uuid

    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    doc_repo = SQLiteDocumentRepository(conn)
    doc_id = str(uuid.uuid4())
    doc_repo.create(doc_id, "Test Doc", "some content", "hash123", None)

    chunk_repo = SQLiteChunkRepository(conn)
    chunk_id = str(uuid.uuid4())
    chunk_repo.create_batch([Chunk(id=chunk_id, document_id=doc_id, chunk_index=0,
                                    text="intro text", offset=0, length=10, section="introduction")])

    chunks = chunk_repo.get_for_document(doc_id)
    assert chunks[0].section == "introduction"


def test_spec_media_type_column(tmp_path):
    """Specs table has media_type for separating text vs image spec lineage."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO specs (id, version, spec_content, media_type) VALUES ('s1', 1, 'spec', 'image')"
    )
    row = conn.execute("SELECT media_type FROM specs WHERE id = 's1'").fetchone()
    assert row["media_type"] == "image"
    # Default is 'text'
    conn.execute("INSERT INTO specs (id, version, spec_content) VALUES ('s2', 1, 'spec')")
    row2 = conn.execute("SELECT media_type FROM specs WHERE id = 's2'").fetchone()
    assert row2["media_type"] == "text"
    conn.close()
