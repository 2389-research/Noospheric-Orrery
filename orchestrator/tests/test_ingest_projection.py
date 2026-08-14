import os
import pytest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("AWS_ACCESS_KEY", "test-key")
os.environ.setdefault("AWS_SECRET_KEY", "test-secret")

from src.db import init_db, recompute_cooccurrence
from src.config import Settings
from src.repositories.sqlite_store import SQLiteDataStore
from src.repositories.factory import set_test_store


MOCK_CLASSIFICATION = {
    "primary_domain": "techniques/wet-blending",
    "secondary_domains": [],
    "new_domains": [],
    "confidence": 0.9,
}

# Two entities sharing one chunk -> exactly one co_occurs edge, weight 1.
MOCK_ENTITIES = [
    {"name": "alpha", "type": "Thing", "chunk_id": "shared"},
    {"name": "beta", "type": "Thing", "chunk_id": "shared"},
]


def _make_store(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    store = SQLiteDataStore(db_path)
    set_test_store(store)
    return store


def _make_settings(tmp_path):
    return Settings(
        aws_access_key="test-key", aws_secret_key="test-secret",
        db_path=str(tmp_path / "test.db"), documents_dir=str(tmp_path / "documents"),
    )


def _valid_edges(conn):
    return sorted((r["from_entity"], r["to_entity"], r["weight"]) for r in conn.execute(
        "SELECT from_entity, to_entity, weight FROM relationships "
        "WHERE type='co_occurs' AND invalid_at IS NULL"))


@pytest.mark.asyncio
async def test_upload_cooccurrence_equals_from_scratch_projection(tmp_path):
    store = _make_store(tmp_path)
    settings = _make_settings(tmp_path)

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.extract_document", new_callable=AsyncMock, return_value=MOCK_ENTITIES), \
         patch("src.routes.ingest.Relay"):
        from src.routes.ingest import _ingest_document
        await _ingest_document(store, "Doc", "Hello world content", None)

    conn = store.conn

    # Every projected edge carries source_chunk = NULL (no per-pair provenance rows).
    assert all(r["source_chunk"] is None for r in conn.execute(
        "SELECT source_chunk FROM relationships WHERE type='co_occurs'"))

    # The single expected edge exists.
    after_ingest = _valid_edges(conn)
    ids = {r["from_entity"] for r in conn.execute("SELECT from_entity FROM relationships WHERE type='co_occurs'")}
    ids |= {r["to_entity"] for r in conn.execute("SELECT to_entity FROM relationships WHERE type='co_occurs'")}
    assert len(after_ingest) == 1 and after_ingest[0][2] == 1

    # The graph equals a from-scratch projection over all active entities.
    all_ids = [r["id"] for r in conn.execute("SELECT id FROM entities WHERE invalid_at IS NULL")]
    conn.execute("DELETE FROM relationships WHERE type='co_occurs' AND invalid_at IS NULL")
    recompute_cooccurrence(conn, all_ids)
    conn.commit()
    assert _valid_edges(conn) == after_ingest

    set_test_store(None)
    store.close()
