import io
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from src.db import init_db
from src.config import Settings


MOCK_CLASSIFICATION = {
    "primary_domain": "techniques/wet-blending",
    "secondary_domains": [],
    "new_domains": [],
    "confidence": 0.9,
}


def make_test_settings(tmp_path):
    return Settings(
        anthropic_api_key="test-key",
        db_path=str(tmp_path / "test.db"),
        documents_dir=str(tmp_path / "documents"),
    )


@pytest.fixture
def client(tmp_path):
    settings = make_test_settings(tmp_path)
    init_db(settings.db_path)

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.main.get_settings", return_value=settings):
        from src.main import app
        with TestClient(app) as c:
            yield c


@pytest.fixture
def client_with_mocked_classify(tmp_path):
    settings = make_test_settings(tmp_path)
    init_db(settings.db_path)

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.main.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION):
        from src.main import app
        with TestClient(app) as c:
            yield c, settings


@pytest.mark.asyncio
async def test_ingest_stores_document(tmp_path):
    settings = make_test_settings(tmp_path)
    init_db(settings.db_path)

    mock_classification = MOCK_CLASSIFICATION

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=mock_classification), \
         patch("src.routes.ingest.AsyncAnthropic"):
        from src.routes.ingest import _ingest_document
        result = await _ingest_document("Test Doc", "Hello world content", None)

    assert "document_id" in result
    assert result["title"] == "Test Doc"

    from src.db import get_connection
    conn = get_connection(settings.db_path)
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (result["document_id"],)).fetchone()
    assert row is not None
    assert row["title"] == "Test Doc"
    assert row["content"] == "Hello world content"
    conn.close()


@pytest.mark.asyncio
async def test_ingest_creates_chunks(tmp_path):
    settings = make_test_settings(tmp_path)
    init_db(settings.db_path)

    long_content = "word " * 1000  # ~5000 chars, should produce multiple chunks at chunk_size=2000

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.AsyncAnthropic"):
        from src.routes.ingest import _ingest_document
        result = await _ingest_document("Chunky Doc", long_content, None)

    from src.db import get_connection
    conn = get_connection(settings.db_path)
    chunks = conn.execute(
        "SELECT * FROM chunks WHERE document_id = ?", (result["document_id"],)
    ).fetchall()
    assert len(chunks) > 1
    conn.close()


@pytest.mark.asyncio
async def test_ingest_assigns_classification(tmp_path):
    settings = make_test_settings(tmp_path)
    init_db(settings.db_path)

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.AsyncAnthropic"):
        from src.routes.ingest import _ingest_document
        result = await _ingest_document("Classified Doc", "Some content about painting", None)

    assert "techniques/wet-blending" in result["domains"]

    from src.db import get_connection
    conn = get_connection(settings.db_path)
    domain_rows = conn.execute(
        "SELECT domain_path FROM document_domains WHERE document_id = ?", (result["document_id"],)
    ).fetchall()
    domain_paths = [r["domain_path"] for r in domain_rows]
    assert "techniques/wet-blending" in domain_paths
    conn.close()


@pytest.mark.asyncio
async def test_ingest_queues_simmer_general_job_when_no_spec(tmp_path):
    settings = make_test_settings(tmp_path)
    init_db(settings.db_path)

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.AsyncAnthropic"):
        from src.routes.ingest import _ingest_document
        result = await _ingest_document("No Spec Doc", "Some content", None)

    assert len(result["jobs_queued"]) > 0

    from src.db import get_connection
    conn = get_connection(settings.db_path)
    job = conn.execute(
        "SELECT * FROM jobs WHERE type = 'simmer_general' AND status = 'queued'"
    ).fetchone()
    assert job is not None
    assert job["id"] in result["jobs_queued"]
    conn.close()


@pytest.mark.asyncio
async def test_ingest_does_not_duplicate_simmer_general_job(tmp_path):
    settings = make_test_settings(tmp_path)
    init_db(settings.db_path)

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.AsyncAnthropic"):
        from src.routes.ingest import _ingest_document
        result1 = await _ingest_document("Doc 1", "Content 1", None)
        result2 = await _ingest_document("Doc 2", "Content 2", None)

    from src.db import get_connection
    conn = get_connection(settings.db_path)
    jobs = conn.execute(
        "SELECT * FROM jobs WHERE type = 'simmer_general'"
    ).fetchall()
    assert len(jobs) == 1  # only one job queued, not duplicated
    conn.close()


@pytest.mark.asyncio
async def test_ingest_skips_extraction_when_no_spec(tmp_path):
    settings = make_test_settings(tmp_path)
    init_db(settings.db_path)

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.AsyncAnthropic"):
        from src.routes.ingest import _ingest_document
        result = await _ingest_document("No Extract Doc", "Content without spec", None)

    assert result["entity_count"] == 0


@pytest.mark.asyncio
async def test_ingest_extracts_entities_when_spec_exists(tmp_path):
    settings = make_test_settings(tmp_path)
    init_db(settings.db_path)

    from src.db import get_connection
    conn = get_connection(settings.db_path)
    import uuid
    conn.execute(
        "INSERT INTO specs (id, domain_path, version, spec_content) VALUES (?, NULL, 1, ?)",
        (str(uuid.uuid4()), "Extract: names and places"),
    )
    conn.commit()
    conn.close()

    mock_entities = [
        {"name": "Citadel", "type": "Brand"},
        {"name": "Abaddon Black", "type": "Paint"},
    ]

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.extract_document", new_callable=AsyncMock, return_value=mock_entities), \
         patch("src.routes.ingest.AsyncAnthropic"):
        from src.routes.ingest import _ingest_document
        result = await _ingest_document("Extract Doc", "Content with entities", None)

    assert result["entity_count"] == 2

    from src.db import get_connection
    conn = get_connection(settings.db_path)
    entities = conn.execute("SELECT * FROM entities").fetchall()
    assert len(entities) == 2
    conn.close()
