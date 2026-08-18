# ABOUTME: POST /ingest/text — the JSON text-ingest entry point used by the MCP ingest tool (#48).
import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("AWS_ACCESS_KEY", "test-key")
os.environ.setdefault("AWS_SECRET_KEY", "test-secret")

from src.config import Settings

MOCK_CLASSIFICATION = {"primary_domain": "techniques/wet-blending",
                       "secondary_domains": [], "new_domains": [], "confidence": 0.9}
MOCK_ENTITIES = [{"name": "citadel", "type": "Brand"}]


def _settings(tmp_path):
    return Settings(aws_access_key="test-key", aws_secret_key="test-secret",
                    db_path=str(tmp_path / "test.db"), documents_dir=str(tmp_path / "documents"))


def test_ingest_text_creates_document(test_client, test_store, tmp_path):
    with patch("src.routes.ingest.get_settings", return_value=_settings(tmp_path)), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.extract_document", new_callable=AsyncMock, return_value=MOCK_ENTITIES), \
         patch("src.routes.ingest.Relay"):
        r = test_client.post("/ingest/text", json={"title": "Note", "content": "hello world about painting"})

    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "Note"
    assert body["entity_count"] == 1
    assert "techniques/wet-blending" in body["domains"]
    # text ingest stores no raw artifact
    row = test_store.conn.execute(
        "SELECT source_path FROM documents WHERE id = ?", (body["document_id"],)).fetchone()
    assert row["source_path"] is None


def test_ingest_text_requires_content(test_client):
    assert test_client.post("/ingest/text", json={"title": "x"}).status_code == 422
