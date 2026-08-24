# ABOUTME: get_entity/get_document/MCP graph-traversal reads surface silo_id + kind,
# ABOUTME: resolved LIVE via the silo_kind view — never a per-doc/per-entity copy.

"""Task 11a: read-path exposure of provenance.

The distinguishing property under test isn't just "the field is present" — it's that
`kind` is resolved fresh on every call. Re-classifying a SOURCE's `provenance_kind`
must change what the very next `get_entity`/`get_document` call reports, with no
re-ingest and no per-row write anywhere near the document or entity itself. That's
what the `_reflects_updated_kind_with_no_reingest` tests pin.
"""

import pytest

import src.mcp_server as mcp_server


def _seed_one_source(store, silo="ws1", kind="neutral_summary"):
    """One watched_source (the silo), one document silo'd to it, one entity sourced
    from that document, all in a domain so nothing here is "unplaceable"."""
    c = store.conn
    c.execute("INSERT INTO watched_sources (id, type, uri, provenance_kind) VALUES (?, 'repo', '/tmp/x', ?)",
              (silo, kind))
    c.execute("INSERT INTO documents (id, title, silo_id) VALUES ('d1', 'Doc One', ?)", (silo,))
    c.execute("INSERT INTO domains (path, document_count) VALUES ('alpha', 1)")
    c.execute("INSERT INTO document_domains (document_id, domain_path, is_primary, confidence) "
              "VALUES ('d1', 'alpha', 1, 1.0)")
    c.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'Entity One', 'Concept')")
    c.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES ('e1', 'd1')")
    c.commit()


# ── get_entity (REST) ─────────────────────────────────────────────────────────

def test_get_entity_sources_include_silo_and_kind(test_client, test_store):
    _seed_one_source(test_store)
    body = test_client.get("/entities/e1").json()
    assert body["sources"][0]["silo_id"] == "ws1"
    assert body["sources"][0]["kind"] == "neutral_summary"


def test_get_entity_source_with_no_silo_reports_none(test_client, test_store):
    c = test_store.conn
    c.execute("INSERT INTO documents (id, title) VALUES ('d1', 'Loose doc')")
    c.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'Loose Entity', 'Concept')")
    c.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES ('e1', 'd1')")
    c.commit()
    body = test_client.get("/entities/e1").json()
    assert body["sources"][0]["silo_id"] is None
    assert body["sources"][0]["kind"] is None


# ── get_document (REST) ───────────────────────────────────────────────────────

def test_get_document_includes_silo_and_kind(test_client, test_store):
    _seed_one_source(test_store)
    body = test_client.get("/documents/d1").json()
    assert body["silo_id"] == "ws1"
    assert body["kind"] == "neutral_summary"


def test_get_document_with_no_silo_has_no_kind(test_client, test_store):
    test_store.conn.execute("INSERT INTO documents (id, title) VALUES ('d2', 'Loose')")
    test_store.conn.commit()
    body = test_client.get("/documents/d2").json()
    assert body["silo_id"] is None
    assert body["kind"] is None


# ── live resolution — no staleness, no re-ingest ──────────────────────────────

def test_get_entity_reflects_updated_kind_with_no_reingest(test_client, test_store):
    _seed_one_source(test_store, silo="ws2", kind="neutral_summary")
    before = test_client.get("/entities/e1").json()
    assert before["sources"][0]["kind"] == "neutral_summary"

    test_store.conn.execute(
        "UPDATE watched_sources SET provenance_kind = 'agent_report' WHERE id = 'ws2'")
    test_store.conn.commit()

    after = test_client.get("/entities/e1").json()
    assert after["sources"][0]["kind"] == "agent_report"
    assert after["sources"][0]["silo_id"] == "ws2"   # untouched — only the kind moved


def test_get_document_reflects_updated_kind_with_no_reingest(test_client, test_store):
    _seed_one_source(test_store, silo="ws3", kind="human_vault")
    before = test_client.get("/documents/d1").json()
    assert before["kind"] == "human_vault"

    test_store.conn.execute(
        "UPDATE watched_sources SET provenance_kind = 'agent_report' WHERE id = 'ws3'")
    test_store.conn.commit()

    after = test_client.get("/documents/d1").json()
    assert after["kind"] == "agent_report"
    assert after["silo_id"] == "ws3"


# ── MCP read path (#48) — the REST endpoint it proxies ────────────────────────

def test_graph_neighborhood_route_annotates_nodes_with_silo_and_kind(test_client, test_store):
    """`/graph/neighborhood` is what the MCP get_neighborhood tool calls."""
    _seed_one_source(test_store, silo="ws4", kind="human_reviewed")
    body = test_client.get("/graph/neighborhood", params={"name": "Entity One", "depth": 1}).json()
    assert body["seed"]["silo_id"] == "ws4"
    assert body["seed"]["kind"] == "human_reviewed"


def test_graph_subgraph_route_annotates_nodes_with_silo_and_kind(test_client, test_store):
    _seed_one_source(test_store, silo="ws5", kind="agent_report")
    body = test_client.post("/graph/subgraph", json={"entity_names": ["Entity One"], "max_hops": 1}).json()
    assert body["seeds"][0]["silo_id"] == "ws5"
    assert body["seeds"][0]["kind"] == "agent_report"


# ── MCP tool text formatting ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mcp_get_entity_surfaces_silo_and_kind(monkeypatch):
    async def fake(path, method="GET", body=None):
        if "neighborhood" in path:
            return {"seed": {"id": "e1"}}
        if "cooccurrences" in path:
            return []
        return {"canonical_name": "Widget", "type": "Concept",
                "sources": [{"document_id": "d1", "silo_id": "ws1", "kind": "agent_report"}]}

    monkeypatch.setattr(mcp_server, "call_api", fake)
    out = await mcp_server.get_entity("Widget")
    assert "ws1" in out and "agent_report" in out


@pytest.mark.asyncio
async def test_mcp_get_neighborhood_surfaces_silo_and_kind(monkeypatch):
    async def fake(path, method="GET", body=None):
        return {
            "seed": {"id": "e1", "name": "Widget", "type": "Concept",
                     "silo_id": "ws1", "kind": "agent_report"},
            "depth": 1, "node_count": 2, "edge_count": 1,
            "nodes": [
                {"id": "e1", "name": "Widget", "type": "Concept", "depth": 0,
                 "source_count": 3, "silo_id": "ws1", "kind": "agent_report"},
                {"id": "e2", "name": "Gadget", "type": "Concept", "depth": 1,
                 "source_count": 1, "silo_id": None, "kind": None},
            ],
            "edges": [],
        }

    monkeypatch.setattr(mcp_server, "call_api", fake)
    out = await mcp_server.get_neighborhood("Widget")
    assert "ws1" in out and "agent_report" in out
    assert "no silo" in out  # the None-silo node is surfaced too, not silently dropped
