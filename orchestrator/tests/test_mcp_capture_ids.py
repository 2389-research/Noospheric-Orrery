# ABOUTME: Issue #93 — MCP read tools emit machine-traceable ids ([query:…]/[entity:…]/[doc:…])
# ABOUTME: so an agent session's graph use can be correlated to exact nodes from its session log.

"""The capture hypothesis (issue #93) needs orrery's MCP outputs to carry stable ids in a
parseable form, mirroring the existing `[image:{document_id}]` convention. These tests pin the
tag FORMAT (so a transcript regex keeps working) and that each read tool emits a fresh query_id
plus the entity/doc ids the graph already knows internally — not the human prose, which is free
to change. If a downstream extractor's regex would stop matching, one of these should fail."""

import re

import pytest

import src.mcp_server as mcp_server

QUERY_RE = re.compile(r"\[query:(qry_[0-9a-f]{32})\]")
ENTITY_RE = re.compile(r"\[entity:([^\]]+)\]")
DOC_RE = re.compile(r"\[doc:([^\]]+)\]")


# ── the small helpers that define the convention ──────────────────────────────

def test_query_id_shape_and_uniqueness():
    a, b = mcp_server._new_query_id(), mcp_server._new_query_id()
    assert QUERY_RE.fullmatch(f"[query:{a}]")
    assert a != b, "each call must mint a distinct correlation id"


def test_eid_did_absent_ids_never_raise_and_emit_nothing():
    # A missing id must degrade to empty string, never a KeyError or a bare "[entity:None]".
    assert mcp_server._eid({}) == ""
    assert mcp_server._eid({"id": None}) == ""
    assert mcp_server._did({}) == ""
    assert mcp_server._eid({"id": "e9"}) == " [entity:e9]"
    assert mcp_server._did({"document_id": "d9"}) == " [doc:d9]"


# ── search_knowledge_graph: header query id + entity ids + chunk doc ids ───────

@pytest.mark.asyncio
async def test_search_emits_query_entity_and_doc_ids(monkeypatch):
    async def fake(path, method="GET", body=None):
        return {
            "query": "widget", "total_entities": 1, "total_chunks": 1,
            "sub_queries_used": [],
            "entities": [{"id": "e1", "name": "Widget", "type": "Concept",
                          "source_count": 2, "score": 1.0, "appearances": 1,
                          "paths": ["exact"], "silo_id": "ws1", "kind": "agent_report"}],
            "chunks": [{"document_id": "d1", "document_title": "Doc One", "text": "...",
                        "entity_overlap": 1, "matching_entities": "Widget",
                        "silo_id": "ws1", "kind": "agent_report"}],
        }

    monkeypatch.setattr(mcp_server, "call_api", fake)
    out = await mcp_server.search_knowledge_graph("widget")
    assert QUERY_RE.search(out), "header must carry a [query:…] correlation id"
    assert "e1" in ENTITY_RE.findall(out)
    assert "d1" in DOC_RE.findall(out)


# ── get_entity: header carries its own id + a query id; co-occurrences carry ids ─

@pytest.mark.asyncio
async def test_get_entity_emits_own_id_and_cooccurrence_ids(monkeypatch):
    async def fake(path, method="GET", body=None):
        if "neighborhood" in path:
            return {"seed": {"id": "e1"}}
        if "cooccurrences" in path:
            return [{"id": "e2", "canonical_name": "Gadget", "type": "Concept", "weight": 3}]
        return {"canonical_name": "Widget", "type": "Concept",
                "sources": [{"document_id": "d1", "silo_id": "ws1", "kind": "agent_report"}]}

    monkeypatch.setattr(mcp_server, "call_api", fake)
    out = await mcp_server.get_entity("Widget")
    assert QUERY_RE.search(out)
    ids = ENTITY_RE.findall(out)
    assert "e1" in ids and "e2" in ids, "both the entity and its co-occurring node are traceable"


# ── get_neighborhood: seed + every hop node carry ids ─────────────────────────

@pytest.mark.asyncio
async def test_get_neighborhood_tags_seed_and_nodes(monkeypatch):
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
    assert QUERY_RE.search(out)
    ids = ENTITY_RE.findall(out)
    assert "e1" in ids and "e2" in ids


# ── the end-to-end shape the capture layer relies on ──────────────────────────

@pytest.mark.asyncio
async def test_one_query_id_groups_the_entities_of_a_single_retrieval(monkeypatch):
    """A downstream extractor slices on [query:…] and collects the [entity:…] under it.
    Prove that a single search response yields exactly one query id and the ids beneath it."""
    async def fake(path, method="GET", body=None):
        return {
            "query": "q", "total_entities": 2, "total_chunks": 0, "sub_queries_used": [],
            "entities": [
                {"id": "e1", "name": "A", "type": "Concept", "source_count": 1,
                 "score": 1.0, "appearances": 1, "paths": [], "silo_id": None, "kind": None},
                {"id": "e2", "name": "B", "type": "Concept", "source_count": 1,
                 "score": 0.9, "appearances": 1, "paths": [], "silo_id": None, "kind": None},
            ],
            "chunks": [],
        }

    monkeypatch.setattr(mcp_server, "call_api", fake)
    out = await mcp_server.search_knowledge_graph("q")
    assert len(QUERY_RE.findall(out)) == 1
    assert set(ENTITY_RE.findall(out)) == {"e1", "e2"}


# ── coverage for the remaining tag-emitting tools (review should-fix #1) ───────
# Each mocks call_api with that tool's real response shape and asserts the query id
# plus the entity/doc ids it should surface. _eid/_did return "" on a missing/renamed
# key, so without these a field rename would drop tags silently with no failing test.

IMAGE_RE = re.compile(r"\[image:([^\]]+)\]")


@pytest.mark.asyncio
async def test_get_document_emits_doc_and_query(monkeypatch):
    async def fake(path, method="GET", body=None):
        if path == "/documents":
            return [{"id": "d1", "title": "Doc One", "content_type": "text"}]
        if "/reader" in path:
            return {"document": {"id": "d1", "title": "Doc One", "content_type": "text",
                                 "domains": ["alpha"]},
                    "entities": [{"id": "e1"}], "total_mentions": 1,
                    "segments": [{"text": "hello world"}]}
        return {}
    monkeypatch.setattr(mcp_server, "call_api", fake)
    out = await mcp_server.get_document("Doc One")
    assert QUERY_RE.search(out)
    assert "d1" in DOC_RE.findall(out)


@pytest.mark.asyncio
async def test_list_entities_emits_entity_and_query(monkeypatch):
    async def fake(path, method="GET", body=None):
        return [{"canonical_name": "A", "type": "Concept", "source_count": 1, "id": "e1"}]
    monkeypatch.setattr(mcp_server, "call_api", fake)
    out = await mcp_server.list_entities()
    assert QUERY_RE.search(out)
    assert "e1" in ENTITY_RE.findall(out)


@pytest.mark.asyncio
async def test_get_shared_context_emits_entities_and_doc(monkeypatch):
    async def fake(path, method="GET", body=None):
        return {
            "entity_a": {"id": "ea", "name": "A", "type": "Concept"},
            "entity_b": {"id": "eb", "name": "B", "type": "Concept"},
            "direct_weight": 2,
            "summary": {"docs_in_common": 1, "neighbors_in_common": 1, "domains_in_common": 1},
            "shared_documents": [{"id": "d1", "title": "Doc"}],
            "shared_neighbors": [{"id": "en", "name": "N", "type": "Concept",
                                  "weight_to_a": 1, "weight_to_b": 1}],
            "shared_domains": ["alpha"],
        }
    monkeypatch.setattr(mcp_server, "call_api", fake)
    out = await mcp_server.get_shared_context("A", "B")
    assert QUERY_RE.search(out)
    ids = ENTITY_RE.findall(out)
    assert {"ea", "eb", "en"} <= set(ids)
    assert "d1" in DOC_RE.findall(out)   # shared documents are now traceable


@pytest.mark.asyncio
async def test_find_paths_emits_path_node_ids(monkeypatch):
    async def fake(path, method="GET", body=None):
        return {"entity_a": {"name": "A"}, "entity_b": {"name": "B"},
                "path_count": 1, "searched_depth": 2,
                "paths": [{"length": 1, "nodes": [
                    {"id": "ea", "name": "A", "type": "Concept"},
                    {"id": "eb", "name": "B", "type": "Concept"}]}]}
    monkeypatch.setattr(mcp_server, "call_api", fake)
    out = await mcp_server.find_paths("A", "B")
    assert QUERY_RE.search(out)
    assert {"ea", "eb"} <= set(ENTITY_RE.findall(out))


@pytest.mark.asyncio
async def test_get_subgraph_emits_seed_and_node_ids(monkeypatch):
    async def fake(path, method="GET", body=None):
        return {"seeds": [{"id": "e1", "name": "A", "type": "Concept",
                           "silo_id": None, "kind": None}],
                "node_count": 2, "edge_count": 1,
                "nodes": [{"id": "e1", "name": "A", "type": "Concept",
                           "silo_id": None, "kind": None, "is_seed": True},
                          {"id": "e2", "name": "B", "type": "Concept",
                           "silo_id": None, "kind": None, "is_seed": False}],
                "edges": [{"source": "e1", "target": "e2", "weight": 3}]}
    monkeypatch.setattr(mcp_server, "call_api", fake)
    out = await mcp_server.get_subgraph(["A"])
    assert QUERY_RE.search(out)
    assert {"e1", "e2"} <= set(ENTITY_RE.findall(out))


@pytest.mark.asyncio
async def test_explore_domain_emits_entity_and_doc(monkeypatch):
    async def fake(path, method="GET", body=None):
        return {"domain": {"path": "alpha", "document_count": 1, "spec_version": None},
                "documents": [{"id": "d1", "title": "Doc", "content_type": "text"}],
                "entity_type_distribution": {"Concept": 2},
                "top_entities": [{"id": "e1", "name": "A", "type": "Concept", "doc_count": 1}],
                "related_domains": [{"path": "beta", "shared_entities": 1}]}
    monkeypatch.setattr(mcp_server, "call_api", fake)
    out = await mcp_server.explore_domain("alpha")
    assert QUERY_RE.search(out)
    assert "e1" in ENTITY_RE.findall(out)
    assert "d1" in DOC_RE.findall(out)


@pytest.mark.asyncio
async def test_search_images_emits_image_and_query(monkeypatch):
    async def fake(path, method="GET", body=None):
        return {"images": [{"document_id": "img1", "title": "Pic", "score": 0.5,
                            "description": "a picture"}]}
    monkeypatch.setattr(mcp_server, "call_api", fake)
    out = await mcp_server.search_images("cat")
    assert QUERY_RE.search(out)
    assert "img1" in IMAGE_RE.findall(out)   # images keep their own [image:] prefix


@pytest.mark.asyncio
async def test_expand_off_by_default_no_subquery_echo(monkeypatch):
    """With expand off, the pipeline reports [query] as its own sole sub-query; the tool
    must NOT echo a redundant 'Sub-queries:' line (review nit #6)."""
    captured = {}
    async def fake(path, method="GET", body=None):
        captured["path"] = path
        return {"query": "widget", "total_entities": 0, "total_chunks": 0,
                "sub_queries_used": ["widget"], "entities": [], "chunks": []}
    monkeypatch.setattr(mcp_server, "call_api", fake)
    out = await mcp_server.search_knowledge_graph("widget")
    assert "expand=false" in captured["path"]   # opt-in expansion is off by default
    assert "Sub-queries:" not in out
