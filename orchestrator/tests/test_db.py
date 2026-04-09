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
