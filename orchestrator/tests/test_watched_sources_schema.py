import os

os.environ.setdefault("AWS_ACCESS_KEY", "test-key")
os.environ.setdefault("AWS_SECRET_KEY", "test-secret")

from src.db import init_db, get_connection


def _cols(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_documents_gains_sync_columns(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    cols = _cols(conn, "documents")
    assert {"modified_at", "invalid_at", "source_id"} <= cols


def test_documents_source_path_index_exists(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_documents_source_path" in names


def test_watched_sources_table_exists_with_spec_columns(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    cols = _cols(conn, "watched_sources")
    assert {
        "id", "type", "uri", "noosphere", "cadence_hours", "config_json",
        "enabled", "last_scanned_at", "last_status", "last_error", "created_at",
    } <= cols


def test_watched_sources_round_trips(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    conn.execute(
        "INSERT INTO watched_sources (id, type, uri, noosphere, cadence_hours, config_json) "
        "VALUES ('w1', 'vault', '/vault', 'ns', 12, '{}')")
    conn.commit()
    row = conn.execute("SELECT * FROM watched_sources WHERE id='w1'").fetchone()
    assert row["type"] == "vault" and row["enabled"] == 1 and row["cadence_hours"] == 12
