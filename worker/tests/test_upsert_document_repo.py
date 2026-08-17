# ABOUTME: upsert_document repo-shaped params — collection membership, role, emits gate,
# ABOUTME: repo-level domain (no per-doc classify), pre-chunked code_intent summaries.

import json
import uuid
from types import SimpleNamespace

import pytest

from src.db import init_db, get_connection, recompute_cooccurrence
from src.config import get_settings
from src.jobs.upsert_document import upsert_document


class FakeRelay:
    """Extraction = one entity per marker word present in the chunk."""
    @classmethod
    def from_settings(cls, settings, **kw):
        return cls()

    async def complete(self, model, max_tokens, messages, **kw):
        text = messages[0]["content"]
        ents = [{"name": n, "type": "Concept"}
                for m, n in (("ALPHA", "alpha"), ("BETA", "beta"),
                             ("GAMMA", "gamma"), ("DELTA", "delta")) if m in text]
        return SimpleNamespace(text=json.dumps({"entities": ents}))

    async def complete_structured(self, model, max_tokens, messages, **kw):
        raise AssertionError("classify must not be called when classify=False")


def _valid_edges(conn):
    out = []
    for r in conn.execute(
        "SELECT ea.canonical_name a, eb.canonical_name b, r.weight w FROM relationships r "
        "JOIN entities ea ON ea.id = r.from_entity JOIN entities eb ON eb.id = r.to_entity "
        "WHERE r.type='co_occurs' AND r.invalid_at IS NULL"):
        pair = tuple(sorted((r["a"], r["b"])))
        out.append((pair[0], pair[1], r["w"]))
    return sorted(out)


async def _leaf(conn, path, content, emits=True, role="leaf"):
    return await upsert_document(
        conn, FakeRelay(), get_settings(), source_path=path, title=path.split("/")[-1],
        content=content, source_id="src1", collection_id="c", role=role,
        parent_path="repo/mod", content_type="code_intent", domain_path="code/repo",
        classify=False, pre_chunked=True, emits_cooccurrence=emits)


@pytest.mark.asyncio
async def test_repo_leaf_shape(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    conn.execute("INSERT INTO collections (id, name, path, root_path) VALUES ('c','repo','repo','/r')")
    conn.commit()

    r = await _leaf(conn, "/r/a.py", "module ALPHA BETA does things")
    assert r["action"] == "created"
    doc_id = r["document_id"]

    dc = conn.execute("SELECT role, emits_cooccurrence FROM document_collections WHERE document_id=?",
                      (doc_id,)).fetchone()
    assert dc["role"] == "leaf" and dc["emits_cooccurrence"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM chunks WHERE document_id=?", (doc_id,)).fetchone()["c"] == 1
    assert conn.execute("SELECT content_type FROM documents WHERE id=?", (doc_id,)).fetchone()["content_type"] == "code_intent"
    assert conn.execute("SELECT domain_path FROM document_domains WHERE document_id=?", (doc_id,)).fetchone()["domain_path"] == "code/repo"
    assert _valid_edges(conn) == [("alpha", "beta", 1)]


@pytest.mark.asyncio
async def test_group_summary_emits_no_hub_edges_even_when_entities_overlap(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    conn.execute("INSERT INTO collections (id, name, path, root_path) VALUES ('c','repo','repo','/r')")
    conn.commit()

    # Leaf emits alpha-beta.
    await _leaf(conn, "/r/a.py", "module ALPHA BETA does things")
    # Group summary (emits=0) mentions ALPHA BETA GAMMA — overlaps the leaf, adds gamma.
    r = await _leaf(conn, "/r/mod", "overview of ALPHA BETA GAMMA", emits=False, role="group")

    assert conn.execute("SELECT emits_cooccurrence FROM document_collections WHERE document_id=?",
                        (r["document_id"],)).fetchone()["emits_cooccurrence"] == 0
    # The group contributes NO edges: only the leaf's alpha-beta survives; no gamma edges,
    # no weight inflation on alpha-beta.
    assert _valid_edges(conn) == [("alpha", "beta", 1)]

    # And a full from-scratch projection agrees (the emits gate holds globally).
    active = [x["id"] for x in conn.execute("SELECT id FROM entities WHERE invalid_at IS NULL")]
    conn.execute("DELETE FROM relationships WHERE type='co_occurs' AND invalid_at IS NULL")
    recompute_cooccurrence(conn, active); conn.commit()
    assert _valid_edges(conn) == [("alpha", "beta", 1)]


@pytest.mark.asyncio
async def test_domain_document_count_is_maintained(tmp_path):
    """The viz layout only positions domains with document_count > 0, so upsert must keep
    that denormalized count fresh across create/update."""
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    conn.execute("INSERT INTO collections (id, name, path, root_path) VALUES ('c','repo','repo','/r')")
    conn.commit()

    def _count(path):
        r = conn.execute("SELECT document_count FROM domains WHERE path=?", (path,)).fetchone()
        return r["document_count"] if r else None

    await _leaf(conn, "/r/a.py", "module ALPHA BETA")     # domain_path='code/repo'
    assert _count("code/repo") == 1
    await _leaf(conn, "/r/b.py", "module GAMMA")          # second doc, same domain
    assert _count("code/repo") == 2


@pytest.mark.asyncio
async def test_repo_leaf_update_refreshes_membership_and_stamps_modified(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    conn.execute("INSERT INTO collections (id, name, path, root_path) VALUES ('c','repo','repo','/r')")
    conn.commit()

    r1 = await _leaf(conn, "/r/a.py", "module ALPHA BETA")
    doc_id = r1["document_id"]
    r2 = await _leaf(conn, "/r/a.py", "module GAMMA DELTA now")   # content changed
    assert r2["action"] == "updated" and r2["document_id"] == doc_id
    assert conn.execute("SELECT modified_at FROM documents WHERE id=?", (doc_id,)).fetchone()["modified_at"] is not None
    # exactly one membership row (refreshed, not duplicated)
    assert conn.execute("SELECT COUNT(*) c FROM document_collections WHERE document_id=?", (doc_id,)).fetchone()["c"] == 1
    assert _valid_edges(conn) == [("delta", "gamma", 1)]
