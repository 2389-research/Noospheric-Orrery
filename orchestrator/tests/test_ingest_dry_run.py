# ABOUTME: Dry-run classifies and extracts a document and persists absolutely nothing.
# ABOUTME: It is the critique surface the charter conversation is built on.

import os
import pytest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("AWS_ACCESS_KEY", "test-key")
os.environ.setdefault("AWS_SECRET_KEY", "test-secret")

from src.db import init_db
from src.config import Settings
from src.repositories.sqlite_store import SQLiteDataStore
from src.repositories.factory import set_test_store

MOCK_CLASSIFICATION = {
    "primary_domain": "legal/contracts",
    "secondary_domains": ["business/finance"],
    "confidence": 0.9,
}
MOCK_ENTITIES = [
    {"name": "acme corp", "type": "Party"},
    {"name": "globex", "type": "Party"},
    {"name": "2026-01-03", "type": "Date"},
]


def make_store(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    store = SQLiteDataStore(db_path)
    set_test_store(store)
    return store


async def _dry_run(store, tmp_path):
    settings = Settings(
        aws_access_key="test-key", aws_secret_key="test-secret",
        db_path=str(tmp_path / "test.db"), documents_dir=str(tmp_path / "documents"),
    )
    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock,
               return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.extract_document", new_callable=AsyncMock,
               return_value=MOCK_ENTITIES), \
         patch("src.routes.ingest.Relay"):
        from src.routes.ingest import _dry_run_document
        return await _dry_run_document(store, "NDA", "Acme Corp agrees to pay Globex.")


@pytest.mark.asyncio
async def test_dry_run_reports_classification_and_types(tmp_path):
    store = make_store(tmp_path)
    result = await _dry_run(store, tmp_path)

    assert result["primary_domain"] == "legal/contracts"
    assert result["secondary_domains"] == ["business/finance"]
    assert result["run_general"] is True

    by_type = {t["type"]: t for t in result["entity_types"]}
    assert by_type["Party"]["count"] == 2
    assert set(by_type["Party"]["examples"]) == {"acme corp", "globex"}
    assert by_type["Date"]["count"] == 1
    set_test_store(None)
    store.close()


@pytest.mark.asyncio
async def test_dry_run_persists_nothing(tmp_path):
    store = make_store(tmp_path)
    await _dry_run(store, tmp_path)

    for table in ("documents", "chunks", "entities", "entity_sources",
                  "domains", "document_domains"):
        count = store.conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
        assert count == 0, f"dry run wrote {count} row(s) to {table}"
    set_test_store(None)
    store.close()


@pytest.mark.asyncio
async def test_dry_run_reports_authored_spec_suppression(tmp_path):
    store = make_store(tmp_path)
    store.domains.create("d1", "legal/contracts", "legal")
    store.specs.create("s1", "legal/contracts", 1, "AUTHORED", source="authored")

    result = await _dry_run(store, tmp_path)
    assert result["run_general"] is False
    assert result["specs_applied"] == ["legal/contracts"]
    set_test_store(None)
    store.close()
