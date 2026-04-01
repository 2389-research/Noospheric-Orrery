import os
import io
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

os.environ.setdefault("AWS_ACCESS_KEY", "test-key")
os.environ.setdefault("AWS_SECRET_KEY", "test-secret")

from src.db import init_db
from src.config import Settings, get_settings
from src.repositories.sqlite_store import SQLiteDataStore
from src.repositories.factory import set_test_store


MOCK_CLASSIFICATION = {
    "primary_domain": "techniques/wet-blending",
    "secondary_domains": [],
    "new_domains": [],
    "confidence": 0.9,
}


def make_test_store(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    store = SQLiteDataStore(db_path)
    set_test_store(store)
    return store


def make_test_settings(tmp_path):
    return Settings(
        aws_access_key="test-key",
        aws_secret_key="test-secret",
        db_path=str(tmp_path / "test.db"),
        documents_dir=str(tmp_path / "documents"),
    )


@pytest.fixture
def client(tmp_path):
    store = make_test_store(tmp_path)
    settings = make_test_settings(tmp_path)
    with patch("src.routes.ingest.get_settings", return_value=settings):
        from src.main import app
        with TestClient(app) as c:
            yield c
    set_test_store(None)
    store.close()


@pytest.fixture
def client_with_mocked_classify(tmp_path):
    store = make_test_store(tmp_path)
    settings = make_test_settings(tmp_path)
    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION):
        from src.main import app
        with TestClient(app) as c:
            yield c, settings
    set_test_store(None)
    store.close()


@pytest.mark.asyncio
async def test_ingest_stores_document(tmp_path):
    store = make_test_store(tmp_path)
    settings = make_test_settings(tmp_path)

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.Relay"):
        from src.routes.ingest import _ingest_document
        result = await _ingest_document(store, "Test Doc", "Hello world content", None)

    assert "document_id" in result
    assert result["title"] == "Test Doc"

    row = store.conn.execute("SELECT * FROM documents WHERE id = ?", (result["document_id"],)).fetchone()
    assert row is not None
    assert row["title"] == "Test Doc"
    assert row["content"] == "Hello world content"
    set_test_store(None)
    store.close()


@pytest.mark.asyncio
async def test_ingest_creates_chunks(tmp_path):
    store = make_test_store(tmp_path)
    settings = make_test_settings(tmp_path)

    long_content = "word " * 1000  # ~5000 chars, should produce multiple chunks at chunk_size=2000

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.Relay"):
        from src.routes.ingest import _ingest_document
        result = await _ingest_document(store, "Chunky Doc", long_content, None)

    conn = store.conn
    chunks = conn.execute(
        "SELECT * FROM chunks WHERE document_id = ?", (result["document_id"],)
    ).fetchall()
    assert len(chunks) > 1
    set_test_store(None)


@pytest.mark.asyncio
async def test_ingest_assigns_classification(tmp_path):
    store = make_test_store(tmp_path)
    settings = make_test_settings(tmp_path)

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.Relay"):
        from src.routes.ingest import _ingest_document
        result = await _ingest_document(store, "Classified Doc", "Some content about painting", None)

    assert "techniques/wet-blending" in result["domains"]

    conn = store.conn
    domain_rows = conn.execute(
        "SELECT domain_path FROM document_domains WHERE document_id = ?", (result["document_id"],)
    ).fetchall()
    domain_paths = [r["domain_path"] for r in domain_rows]
    assert "techniques/wet-blending" in domain_paths
    set_test_store(None)


@pytest.mark.asyncio
async def test_ingest_queues_simmer_general_job_when_no_spec(tmp_path):
    store = make_test_store(tmp_path)
    settings = make_test_settings(tmp_path)

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.Relay"):
        from src.routes.ingest import _ingest_document
        result = await _ingest_document(store, "No Spec Doc", "Some content", None)

    assert len(result["jobs_queued"]) > 0

    conn = store.conn
    job = conn.execute(
        "SELECT * FROM jobs WHERE type = 'simmer_general' AND status = 'queued'"
    ).fetchone()
    assert job is not None
    assert job["id"] in result["jobs_queued"]
    set_test_store(None)


@pytest.mark.asyncio
async def test_ingest_does_not_duplicate_simmer_general_job(tmp_path):
    store = make_test_store(tmp_path)
    settings = make_test_settings(tmp_path)

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.Relay"):
        from src.routes.ingest import _ingest_document
        result1 = await _ingest_document(store, "Doc 1", "Content 1", None)
        result2 = await _ingest_document(store, "Doc 2", "Content 2", None)

    conn = store.conn
    jobs = conn.execute(
        "SELECT * FROM jobs WHERE type = 'simmer_general'"
    ).fetchall()
    assert len(jobs) == 1  # only one job queued, not duplicated
    set_test_store(None)


@pytest.mark.asyncio
async def test_ingest_skips_extraction_when_no_spec(tmp_path):
    store = make_test_store(tmp_path)
    settings = make_test_settings(tmp_path)

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.Relay"):
        from src.routes.ingest import _ingest_document
        result = await _ingest_document(store, "No Extract Doc", "Content without spec", None)

    assert result["entity_count"] == 0


@pytest.mark.asyncio
async def test_ingest_extracts_entities_when_spec_exists(tmp_path):
    store = make_test_store(tmp_path)
    settings = make_test_settings(tmp_path)

    conn = store.conn
    import uuid
    conn.execute(
        "INSERT INTO specs (id, domain_path, version, spec_content) VALUES (?, NULL, 1, ?)",
        (str(uuid.uuid4()), "Extract: names and places"),
    )
    conn.commit()

    mock_entities = [
        {"name": "Citadel", "type": "Brand"},
        {"name": "Abaddon Black", "type": "Paint"},
    ]

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.extract_document", new_callable=AsyncMock, return_value=mock_entities), \
         patch("src.routes.ingest.Relay"):
        from src.routes.ingest import _ingest_document
        result = await _ingest_document(store, "Extract Doc", "Content with entities", None)

    assert result["entity_count"] == 2

    conn = store.conn
    entities = conn.execute("SELECT * FROM entities").fetchall()
    assert len(entities) == 2
    set_test_store(None)
