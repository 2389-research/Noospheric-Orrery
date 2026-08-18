# ABOUTME: MCP write tools (#48) proxy the right REST endpoints and format results sanely.
import pytest

import src.mcp_server as mcp_server


@pytest.mark.asyncio
async def test_ingest_text_posts_to_endpoint(monkeypatch):
    seen = {}

    async def fake(path, method="GET", body=None):
        seen.update(path=path, method=method, body=body)
        return {"document_id": "d1", "title": "Note", "domains": ["a/b"], "entity_count": 3}

    monkeypatch.setattr(mcp_server, "call_api", fake)
    out = await mcp_server.ingest_text("Note", "hello")
    assert seen == {"path": "/ingest/text", "method": "POST",
                    "body": {"title": "Note", "content": "hello"}}
    assert "d1" in out and "3 entities" in out


@pytest.mark.asyncio
async def test_ingest_text_reports_failure(monkeypatch):
    async def fake(path, **k):
        return {"status": 500, "detail": "boom"}

    monkeypatch.setattr(mcp_server, "call_api", fake)
    out = await mcp_server.ingest_text("x", "y")
    assert "fail" in out.lower() and "boom" in out


@pytest.mark.asyncio
async def test_create_noosphere(monkeypatch):
    async def fake(path, method="GET", body=None):
        assert path == "/workspaces" and method == "POST"
        return {"workspaceId": "ws1", "name": body["name"]}

    monkeypatch.setattr(mcp_server, "call_api", fake)
    out = await mcp_server.create_noosphere("My WS", "desc")
    assert "ws1" in out and "My WS" in out


@pytest.mark.asyncio
async def test_trigger_simmer_general_vs_domain(monkeypatch):
    paths = []

    async def fake(path, method="GET", body=None):
        paths.append(path)
        return {"job_id": "j1"}

    monkeypatch.setattr(mcp_server, "call_api", fake)
    await mcp_server.trigger_simmer()
    await mcp_server.trigger_simmer("techniques/wet-blending")
    assert paths == ["/simmer/general", "/simmer/techniques/wet-blending"]


@pytest.mark.asyncio
async def test_trigger_normalization(monkeypatch):
    async def fake(path, method="GET", body=None):
        assert path == "/normalize" and method == "POST"
        return {"merged": 3, "review_queued": 1}

    monkeypatch.setattr(mcp_server, "call_api", fake)
    out = await mcp_server.trigger_normalization()
    assert "complete" in out.lower()


@pytest.mark.asyncio
async def test_get_job_status_single_with_progress(monkeypatch):
    async def fake(path, **k):
        assert path == "/jobs/j1"
        return {"id": "j1", "type": "extract_batch", "status": "running",
                "progress": {"docs_done": 2, "docs_total": 6, "entities_so_far": 40}, "results": None}

    monkeypatch.setattr(mcp_server, "call_api", fake)
    out = await mcp_server.get_job_status("j1")
    assert "2/6" in out and "running" in out


@pytest.mark.asyncio
async def test_get_job_status_lists_only_active(monkeypatch):
    async def fake(path, **k):
        return [
            {"id": "j1", "type": "extract_batch", "status": "running",
             "progress": {"docs_done": 1, "docs_total": 3}},
            {"id": "j2", "type": "simmer_general", "status": "completed"},
        ]

    monkeypatch.setattr(mcp_server, "call_api", fake)
    out = await mcp_server.get_job_status()
    assert "j1" in out and "j2" not in out
