# ABOUTME: An authored spec replaces the general extraction pass for its domain.
# ABOUTME: With no authored spec anywhere, ingest must behave exactly as it did before.

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
    "secondary_domains": [],
    "confidence": 0.9,
}
MOCK_ENTITIES = [{"name": "acme corp", "type": "Party"}]


def make_store(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    store = SQLiteDataStore(db_path)
    set_test_store(store)
    return store


def make_settings(tmp_path):
    return Settings(
        aws_access_key="test-key", aws_secret_key="test-secret",
        db_path=str(tmp_path / "test.db"),
        documents_dir=str(tmp_path / "documents"),
    )


async def _run_ingest(store, tmp_path, extract_mock):
    with patch("src.routes.ingest.get_settings", return_value=make_settings(tmp_path)), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock,
               return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.extract_document", new=extract_mock), \
         patch("src.routes.ingest.Relay"):
        from src.routes.ingest import _ingest_document
        return await _ingest_document(store, "NDA", "Acme Corp agrees to...", None)


@pytest.mark.asyncio
async def test_no_authored_spec_runs_general_pass(tmp_path):
    store = make_store(tmp_path)
    extract = AsyncMock(return_value=MOCK_ENTITIES)
    await _run_ingest(store, tmp_path, extract)

    specs_used = [c.kwargs["spec"] for c in extract.await_args_list]
    assert len(specs_used) == 1, "general pass should run exactly once"

    passes = {r["extraction_pass"] for r in
              store.conn.execute("SELECT extraction_pass FROM entity_sources").fetchall()}
    assert passes == {"general"}
    set_test_store(None)
    store.close()


@pytest.mark.asyncio
async def test_authored_spec_replaces_general_pass(tmp_path):
    store = make_store(tmp_path)
    store.domains.create("d1", "legal/contracts", "legal")
    store.specs.create("s1", "legal/contracts", 1, "MY AUTHORED SPEC", source="authored")

    extract = AsyncMock(return_value=MOCK_ENTITIES)
    await _run_ingest(store, tmp_path, extract)

    specs_used = [c.kwargs["spec"] for c in extract.await_args_list]
    assert specs_used == ["MY AUTHORED SPEC"], "only the authored spec should run"

    passes = {r["extraction_pass"] for r in
              store.conn.execute("SELECT extraction_pass FROM entity_sources").fetchall()}
    assert passes == {"domain-specific"}
    set_test_store(None)
    store.close()


@pytest.mark.asyncio
async def test_simmered_spec_runs_alongside_general(tmp_path):
    store = make_store(tmp_path)
    store.domains.create("d1", "legal/contracts", "legal")
    store.specs.create("s1", "legal/contracts", 1, "SIMMERED SPEC", source="simmered")

    extract = AsyncMock(return_value=MOCK_ENTITIES)
    await _run_ingest(store, tmp_path, extract)

    specs_used = [c.kwargs["spec"] for c in extract.await_args_list]
    assert len(specs_used) == 2, "general pass plus the simmered domain spec"
    assert "SIMMERED SPEC" in specs_used
    set_test_store(None)
    store.close()
