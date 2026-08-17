# ABOUTME: extract_batch writes co_occurs as a pure projection of entity_sources.
# ABOUTME: Guards the emits-gate under entity overlap between a leaf and a summary doc.

import json
import uuid
from types import SimpleNamespace

import pytest

from src.db import init_db, get_connection, recompute_cooccurrence


def _fake_complete(model, max_tokens, messages):
    """Leaf chunk -> {alpha, beta}; summary chunk -> {alpha, beta, gamma} (overlap)."""
    content = messages[0]["content"]
    if "LEAF_CHUNK" in content:
        entities = [{"name": "alpha", "type": "Thing"}, {"name": "beta", "type": "Thing"}]
    else:
        entities = [{"name": "alpha", "type": "Thing"}, {"name": "beta", "type": "Thing"},
                    {"name": "gamma", "type": "Thing"}]
    return SimpleNamespace(text=json.dumps({"entities": entities}))


class FakeRelay:
    @classmethod
    def from_settings(cls, settings, **overrides):
        return cls()

    async def complete(self, model, max_tokens, messages, **kwargs):
        return _fake_complete(model, max_tokens, messages)


def _valid_edges(conn):
    return sorted((r["from_entity"], r["to_entity"], r["weight"]) for r in conn.execute(
        "SELECT from_entity, to_entity, weight FROM relationships "
        "WHERE type='co_occurs' AND invalid_at IS NULL"))


@pytest.mark.asyncio
async def test_extract_batch_projects_and_honours_emits_under_overlap(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)

    collection_id, spec_id = str(uuid.uuid4()), "spec1"
    leaf_id, summary_id = str(uuid.uuid4()), str(uuid.uuid4())

    conn = get_connection(db_path)
    conn.execute("INSERT INTO collections (id, name, path, root_path) VALUES (?,?,?,?)",
                 (collection_id, "repo", "repo", str(tmp_path)))
    conn.execute("INSERT INTO specs (id, domain_path, version, spec_content) VALUES (?, NULL, 1, ?)",
                 (spec_id, "Extract entities."))

    # Leaf doc — emits.
    conn.execute("INSERT INTO documents (id, content, status, content_type) VALUES (?,?, 'classified', 'code_intent')",
                 (leaf_id, "leaf"))
    conn.execute("INSERT INTO chunks (id, document_id, chunk_index, offset, length, text) VALUES (?,?,0,0,?,?)",
                 (str(uuid.uuid4()), leaf_id, 9, "LEAF_CHUNK: x"))
    conn.execute("INSERT INTO document_collections (document_id, collection_id, parent_path, role, "
                 "emits_cooccurrence) VALUES (?,?,?,'leaf',1)", (leaf_id, collection_id, "repo/a.py"))

    # Summary doc — does NOT emit, but shares alpha/beta with the leaf and adds gamma.
    conn.execute("INSERT INTO documents (id, content, status, content_type) VALUES (?,?, 'classified', 'code_intent')",
                 (summary_id, "summary"))
    conn.execute("INSERT INTO chunks (id, document_id, chunk_index, offset, length, text) VALUES (?,?,0,0,?,?)",
                 (str(uuid.uuid4()), summary_id, 12, "SUMMARY_CHUNK: x"))
    conn.execute("INSERT INTO document_collections (document_id, collection_id, parent_path, role, "
                 "emits_cooccurrence) VALUES (?,?,?,'group',0)", (summary_id, collection_id, "repo/mod"))
    conn.commit()
    conn.close()

    import src.jobs.extract_batch as extract_batch_mod
    monkeypatch.setattr(extract_batch_mod, "Relay", FakeRelay)
    from src.jobs.extract_batch import run_extract_batch

    await run_extract_batch({"id": str(uuid.uuid4()),
                             "config": json.dumps({"spec_id": spec_id, "scope": "code_intent"})}, db_path)

    conn = get_connection(db_path)

    # Both docs sourced their entities.
    assert conn.execute("SELECT COUNT(*) c FROM entity_sources WHERE document_id=?", (summary_id,)).fetchone()["c"] >= 3

    edges = _valid_edges(conn)
    # Only the leaf's alpha-beta edge, weight 1. The summary (emits=0) contributes
    # nothing: no gamma edge, and alpha-beta is NOT inflated to 2.
    gamma_ids = {r["entity_id"] for r in conn.execute(
        "SELECT entity_id FROM entity_sources es JOIN entities e ON e.id=es.entity_id "
        "WHERE e.canonical_name='gamma'")}
    assert all(g not in (f, t) for (f, t, _w) in edges for g in gamma_ids)
    assert [(f_t_w[2]) for f_t_w in edges] == [1]
    assert len(edges) == 1

    # Pure projection: source_chunk NULL, and equal to a from-scratch recompute.
    assert all(r["source_chunk"] is None for r in conn.execute(
        "SELECT source_chunk FROM relationships WHERE type='co_occurs'"))
    active = [r["id"] for r in conn.execute("SELECT id FROM entities WHERE invalid_at IS NULL")]
    conn.execute("DELETE FROM relationships WHERE type='co_occurs' AND invalid_at IS NULL")
    recompute_cooccurrence(conn, active)
    conn.commit()
    assert _valid_edges(conn) == edges
    conn.close()
