"""Lock in RFC-conformant status codes on creation endpoints.

From issue #7 (Derek): POST endpoints that create resources should return
201 Created with a Location header, not 200 OK. These tests fail the
build if anyone reverts that.
"""

import io
from unittest.mock import AsyncMock, patch


MOCK_CLASSIFICATION = {
    "primary_domain": "test/domain",
    "secondary_domains": [],
    "new_domains": [],
    "confidence": 0.9,
}


def test_create_workspace_returns_201_with_location(test_client):
    resp = test_client.post("/workspaces", json={"name": "rest-hygiene-test"})
    assert resp.status_code == 201
    body = resp.json()
    ws_id = body["workspaceId"]
    assert resp.headers.get("Location") == f"/workspaces/{ws_id}"


def test_ingest_returns_201_with_location(test_client):
    """POST /ingest creates a document resource; should be 201 + Location.

    Mocks the LLM-touching pipeline so the test stays fast and offline.
    """
    files = {"file": ("note.txt", io.BytesIO(b"hello world"), "text/plain")}
    with patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.extract_document", new_callable=AsyncMock, return_value=[]), \
         patch("src.routes.ingest.Relay"):
        resp = test_client.post("/ingest", files=files)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    doc_id = body["document_id"]
    assert resp.headers.get("Location") == f"/documents/{doc_id}"
