# ABOUTME: specs.source carries the authored/simmered contract, not just provenance.
# ABOUTME: Authored specs are complete; simmered ones are additive. Defaults must not shift.

import os
import pytest

os.environ.setdefault("AWS_ACCESS_KEY", "test-key")
os.environ.setdefault("AWS_SECRET_KEY", "test-secret")

from src.db import init_db, get_connection
from src.repositories.sqlite_store import SQLiteDataStore


def test_spec_defaults_to_simmered(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    store = SQLiteDataStore(db_path)
    store.specs.create("s1", "legal/contracts", 1, "content")
    spec = store.specs.get_for_domain("legal/contracts")
    assert spec.source == "simmered"
    store.close()


def test_spec_can_be_authored(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    store = SQLiteDataStore(db_path)
    store.specs.create("s1", "legal/contracts", 1, "content", source="authored")
    spec = store.specs.get_for_domain("legal/contracts")
    assert spec.source == "authored"
    store.close()


def test_general_spec_carries_source(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    store = SQLiteDataStore(db_path)
    store.specs.create("s1", None, 1, "general content")
    assert store.specs.get_general().source == "simmered"
    store.close()


def test_migration_backfills_existing_rows(tmp_path):
    """A database created before this column must gain it with the safe default."""
    db_path = str(tmp_path / "legacy.db")
    conn = get_connection(db_path)
    conn.executescript("""
        CREATE TABLE specs (
            id TEXT PRIMARY KEY, domain_path TEXT, version INTEGER,
            spec_content TEXT, golden_set TEXT, score REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.execute("INSERT INTO specs (id, domain_path, version, spec_content) VALUES ('old', 'a/b', 1, 'x')")
    conn.commit()
    conn.close()

    init_db(db_path)

    store = SQLiteDataStore(db_path)
    assert store.specs.get_for_domain("a/b").source == "simmered"
    store.close()
