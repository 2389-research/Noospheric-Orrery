# ABOUTME: ccvault ingestion (docs/ccvault-ingestion.md) — a session is recursively summarized
# ABOUTME: into the ONE ccvault silo: a 'group' doc (rollup) over 'leaf' docs (segments); graph-using
# ABOUTME: segments become entity-anchored active_work leaves; order via turn_next edges.

import asyncio
import json
import sqlite3
import uuid

import pytest

import src.jobs.ingest_ccvault as mod
from src.jobs import ccvault_reader
from src.db import get_connection


# ── fixtures / builders ────────────────────────────────────────────────────────

def _make_ccvault_db(path):
    """Two claude-code sessions + one codex; sess-1 has user/assistant content (no graph),
    sess-2 is content-less, sess-3 is codex (excluded by the default source filter)."""
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE projects (id INTEGER PRIMARY KEY, path TEXT);
        CREATE TABLE sessions (id TEXT PRIMARY KEY, project_id INTEGER, started_at TEXT, turn_count INTEGER, source TEXT);
        CREATE TABLE turns (id TEXT PRIMARY KEY, session_id TEXT, parent_id TEXT, type TEXT, timestamp TEXT, content TEXT, raw_json BLOB);
        CREATE TABLE tool_uses (id INTEGER PRIMARY KEY, turn_id TEXT, session_id TEXT, tool_name TEXT, timestamp TEXT);
    """)
    c.execute("INSERT INTO projects (id, path) VALUES (1, '/home/u/proj-alpha')")
    c.execute("INSERT INTO sessions VALUES ('sess-1', 1, '2026-09-01 10:00:00', 2, 'claude-code')")
    c.execute("INSERT INTO turns VALUES ('t1','sess-1',NULL,'user','2026-09-01 10:00:01','Investigate the auth module', NULL)")
    c.execute("INSERT INTO turns VALUES ('t2','sess-1','t1','assistant','2026-09-01 10:00:02','Looked at auth.py and found the token check', NULL)")
    c.execute("INSERT INTO sessions VALUES ('sess-2', 1, '2026-09-01 11:00:00', 1, 'claude-code')")
    c.execute("INSERT INTO turns VALUES ('t3','sess-2',NULL,'system','2026-09-01 11:00:01','boot', NULL)")
    c.execute("INSERT INTO sessions VALUES ('sess-3', 1, '2026-09-01 12:00:00', 1, 'codex')")
    c.execute("INSERT INTO turns VALUES ('t4','sess-3',NULL,'user','2026-09-01 12:00:01','hi from codex', NULL)")
    c.commit(); c.close()


class _Resp:
    def __init__(self, text): self.text = text


class _FakeRelay:
    async def complete(self, model, max_tokens, messages):
        return _Resp("Neutral summary: the session examined the auth module and its token check.")

    @classmethod
    def from_settings(cls, settings, **kw):
        return cls()


class _EmptyRelay:
    async def complete(self, model, max_tokens, messages):
        return _Resp("")   # local models can return empty .text without raising

    @classmethod
    def from_settings(cls, settings, **kw):
        return cls()


def _stub(monkeypatch, domain="software/auth"):
    async def fake_classify(relay, title, excerpt, existing_taxonomy, model):
        return {"primary_domain": domain, "secondary_domains": []}
    monkeypatch.setattr(mod, "classify_document", fake_classify)
    monkeypatch.setattr(mod, "Relay", _FakeRelay)


def _seed_collection(db_path, collection_id):
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO collections (id, name, path, root_path, kind, provenance_kind, document_count) "
        "VALUES (?, 'ccvault', 'ccvault', '/tmp/cc', 'ccvault', 'agent_report', 0)", (collection_id,))
    conn.commit(); conn.close()


def _seed_entity(db_path, eid="ent-auth", name="Auth"):
    conn = get_connection(db_path)
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES (?, ?, 'Concept')", (eid, name))
    conn.commit(); conn.close()


def _job(archive_path, collection_id, db_path=None):
    job = {"id": str(uuid.uuid4()), "type": "ingest_ccvault", "target": collection_id,
           "config": json.dumps({"archive_path": archive_path, "collection_id": collection_id, "spec_id": "spec-x"})}
    if db_path:
        conn = get_connection(db_path)
        conn.execute("INSERT INTO jobs (id, type, target, status, config) VALUES (?, ?, ?, 'running', ?)",
                     (job["id"], job["type"], job["target"], job["config"]))
        conn.commit(); conn.close()
    return job


def _roles(conn, collection_id):
    return [dict(role=r[0], ctype=r[1], parent=r[2], doc=r[3]) for r in conn.execute(
        "SELECT dc.role, d.content_type, dc.parent_path, dc.document_id FROM document_collections dc "
        "JOIN documents d ON d.id = dc.document_id WHERE dc.collection_id = ?", (collection_id,))]


# ── reader: segmentation ────────────────────────────────────────────────────────

def test_iter_segments_splits_and_carries_ids(tmp_path):
    _make_ccvault_db(str(tmp_path / "ccvault.db"))
    conn = ccvault_reader.open_archive(str(tmp_path / "ccvault.db"))
    try:
        segs = ccvault_reader.iter_segments(conn, "sess-1")
        assert len(segs) >= 1
        assert "auth module" in " ".join(s["text"] for s in segs)
        assert all(s["is_graph_work"] is False for s in segs)  # no graph ids in sess-1
        assert ccvault_reader.iter_segments(conn, "sess-2") == []  # no user/assistant content
    finally:
        conn.close()


# ── recursive structure: group (rollup) over leaves (segments) ──────────────────

def test_session_becomes_group_over_leaves(tmp_path, monkeypatch, test_db):
    _stub(monkeypatch)
    arcp = str(tmp_path / "ccvault.db"); _make_ccvault_db(arcp)
    cid = str(uuid.uuid4()); _seed_collection(test_db, cid)

    asyncio.run(mod.run_ingest_ccvault(_job(arcp, cid, test_db), test_db))

    conn = get_connection(test_db)
    try:
        docs = _roles(conn, cid)
        groups = [d for d in docs if d["role"] == "group"]
        leaves = [d for d in docs if d["role"] == "leaf"]
        assert len(groups) == 1 and groups[0]["ctype"] == "session_intent"
        assert len(leaves) >= 1 and all(l["ctype"] == "session_intent" for l in leaves)
        # leaves bucket under the session group (render contract: leaf.parent_path == group title)
        gtitle = conn.execute("SELECT title FROM documents WHERE id=?", (groups[0]["doc"],)).fetchone()[0]
        assert all(l["parent"] == gtitle for l in leaves)
        # one silo, agent_report
        assert conn.execute("SELECT kind FROM silo_kind WHERE silo_id=?", (cid,)).fetchone()[0] == "agent_report"
        assert all(conn.execute("SELECT silo_id FROM documents WHERE id=?", (d["doc"],)).fetchone()[0] == cid for d in docs)
        # both sessions watermarked (sess-2 empty)
        seen = {r[0] for r in conn.execute("SELECT session_id FROM ccvault_sessions_seen")}
        assert seen == {"sess-1", "sess-2"}
        # extract_batch enqueued for the session_intent docs
        eb = conn.execute("SELECT config FROM jobs WHERE type='extract_batch'").fetchone()
        assert eb and json.loads(eb[0])["scope"] == "session_intent"
    finally:
        conn.close()


def test_reingest_is_noop(tmp_path, monkeypatch, test_db):
    _stub(monkeypatch)
    arcp = str(tmp_path / "ccvault.db"); _make_ccvault_db(arcp)
    cid = str(uuid.uuid4()); _seed_collection(test_db, cid)

    asyncio.run(mod.run_ingest_ccvault(_job(arcp, cid, test_db), test_db))
    n1 = get_connection(test_db).execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    job2 = _job(arcp, cid, test_db)
    asyncio.run(mod.run_ingest_ccvault(job2, test_db))

    conn = get_connection(test_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == n1  # no dupes
        assert json.loads(conn.execute("SELECT result FROM jobs WHERE id=?", (job2["id"],)).fetchone()[0])["sessions_ingested"] == 0
    finally:
        conn.close()


# ── Flow B: graph-using segment → active_work leaf (MCP tags) ────────────────────

_QID = "qry_" + "a" * 32


def _make_ccvault_db_tags(path, entity_tag="ent-auth", query_id=_QID):
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE projects (id INTEGER PRIMARY KEY, path TEXT);
        CREATE TABLE sessions (id TEXT PRIMARY KEY, project_id INTEGER, started_at TEXT, turn_count INTEGER, source TEXT);
        CREATE TABLE turns (id TEXT PRIMARY KEY, session_id TEXT, parent_id TEXT, type TEXT, timestamp TEXT, content TEXT, raw_json BLOB);
        CREATE TABLE tool_uses (id INTEGER PRIMARY KEY, turn_id TEXT, session_id TEXT, tool_name TEXT, timestamp TEXT);
    """)
    c.execute("INSERT INTO projects (id, path) VALUES (1, '/home/u/proj-auth')")
    c.execute("INSERT INTO sessions VALUES ('sess-g', 1, '2026-09-01 10:00:00', 3, 'claude-code')")
    tu = {"message": {"role": "assistant", "content": [
        {"type": "text", "text": "Let me look up Auth."},
        {"type": "tool_use", "id": "tu1", "name": "mcp__noospheric-orrery__get_entity", "input": {"name": "Auth"}}]}}
    tr = {"message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "tu1",
         "content": f"Auth (Concept) [entity:{entity_tag}] [query:{query_id}]\nSources: 1 mention"}]}}
    syn = {"message": {"role": "assistant", "content": [{"type": "text", "text": "Auth relies on token checks."}]}}
    c.execute("INSERT INTO turns VALUES ('g1','sess-g',NULL,'assistant','2026-09-01 10:00:01','Let me look up Auth.', ?)", (json.dumps(tu),))
    c.execute("INSERT INTO turns VALUES ('g2','sess-g','g1','user','2026-09-01 10:00:02','[tool result]', ?)", (json.dumps(tr),))
    c.execute("INSERT INTO turns VALUES ('g3','sess-g','g2','assistant','2026-09-01 10:00:03','Auth relies on token checks.', ?)", (json.dumps(syn),))
    c.execute("INSERT INTO tool_uses VALUES (1,'g1','sess-g','mcp__noospheric-orrery__get_entity','2026-09-01 10:00:01')")
    c.commit(); c.close()


def test_graph_segment_becomes_active_work_leaf(tmp_path, monkeypatch, test_db):
    _stub(monkeypatch)
    arcp = str(tmp_path / "ccvault.db"); _make_ccvault_db_tags(arcp)
    cid = str(uuid.uuid4()); _seed_collection(test_db, cid); _seed_entity(test_db, "ent-auth", "Auth")

    asyncio.run(mod.run_ingest_ccvault(_job(arcp, cid, test_db), test_db))

    conn = get_connection(test_db)
    try:
        docs = _roles(conn, cid)
        assert any(d["role"] == "group" and d["ctype"] == "session_intent" for d in docs)  # session rollup
        aw = [d for d in docs if d["ctype"] == "active_work"]
        assert len(aw) == 1 and aw[0]["role"] == "leaf"
        # active_work leaf is entity-anchored (chunk-less link) AND chunked for semantic recall
        link = conn.execute("SELECT chunk_id FROM entity_sources WHERE entity_id='ent-auth' AND document_id=?",
                            (aw[0]["doc"],)).fetchone()
        assert link is not None and link[0] is None
        assert conn.execute("SELECT COUNT(*) FROM chunks WHERE document_id=?", (aw[0]["doc"],)).fetchone()[0] == 1
        # query_id ledger points at the active_work leaf
        assert conn.execute("SELECT document_id FROM ccvault_processed WHERE query_id=?", (_QID,)).fetchone()[0] == aw[0]["doc"]
    finally:
        conn.close()


def test_graph_segment_unresolved_entity_becomes_neutral_leaf(tmp_path, monkeypatch, test_db):
    """A graph segment whose entity ids don't resolve here still gets captured as a neutral
    session_intent leaf (not active_work), and its query_id is recorded so it's not reprocessed."""
    _stub(monkeypatch)
    arcp = str(tmp_path / "ccvault.db"); _make_ccvault_db_tags(arcp)
    cid = str(uuid.uuid4()); _seed_collection(test_db, cid)  # NO entity seeded

    asyncio.run(mod.run_ingest_ccvault(_job(arcp, cid, test_db), test_db))

    conn = get_connection(test_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM documents WHERE content_type='active_work'").fetchone()[0] == 0
        pr = conn.execute("SELECT document_id FROM ccvault_processed WHERE query_id=?", (_QID,)).fetchone()
        assert pr is not None and pr[0] is not None  # recorded, pointing at the neutral leaf
    finally:
        conn.close()


# ── Flow B via BARE API (no MCP): ids from raw JSON in a Bash tool_result ───────

_QID_BARE = "qry_" + "c" * 32


def _make_ccvault_db_bare_api(path, entity_id="ent-auth", query_id=_QID_BARE):
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE projects (id INTEGER PRIMARY KEY, path TEXT);
        CREATE TABLE sessions (id TEXT PRIMARY KEY, project_id INTEGER, started_at TEXT, turn_count INTEGER, source TEXT);
        CREATE TABLE turns (id TEXT PRIMARY KEY, session_id TEXT, parent_id TEXT, type TEXT, timestamp TEXT, content TEXT, raw_json BLOB);
        CREATE TABLE tool_uses (id INTEGER PRIMARY KEY, turn_id TEXT, session_id TEXT, tool_name TEXT, timestamp TEXT);
    """)
    c.execute("INSERT INTO sessions VALUES ('sess-b', 1, '2026-09-03', 3, 'claude-code')")
    tu = {"message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "b1", "name": "Bash", "input": {"command": "curl -s http://127.0.0.1:8100/search?q=auth"}}]}}
    api_json = json.dumps({"query": "auth", "total_entities": 1,
                           "entities": [{"id": entity_id, "name": "Auth", "type": "Concept"}], "query_id": query_id})
    tr = {"message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "b1", "content": api_json}]}}
    syn = {"message": {"role": "assistant", "content": [{"type": "text", "text": "Auth is a Concept with one source."}]}}
    c.execute("INSERT INTO turns VALUES ('a','sess-b',NULL,'assistant','t1','curl', ?)", (json.dumps(tu).encode(),))
    c.execute("INSERT INTO turns VALUES ('b','sess-b','a','user','t2','[result]', ?)", (json.dumps(tr).encode(),))
    c.execute("INSERT INTO turns VALUES ('c','sess-b','b','assistant','t3','Auth is a Concept.', ?)", (json.dumps(syn).encode(),))
    c.execute("INSERT INTO tool_uses VALUES (1,'a','sess-b','Bash','t1')")
    c.commit(); c.close()


def test_bare_api_segment_becomes_active_work_leaf(tmp_path, monkeypatch, test_db):
    _stub(monkeypatch)
    arcp = str(tmp_path / "ccvault.db"); _make_ccvault_db_bare_api(arcp)
    cid = str(uuid.uuid4()); _seed_collection(test_db, cid); _seed_entity(test_db, "ent-auth", "Auth")

    asyncio.run(mod.run_ingest_ccvault(_job(arcp, cid, test_db), test_db))

    conn = get_connection(test_db)
    try:
        aw = conn.execute("SELECT id FROM documents WHERE content_type='active_work'").fetchone()
        assert aw is not None
        assert conn.execute("SELECT 1 FROM entity_sources WHERE entity_id='ent-auth' AND document_id=?",
                            (aw[0],)).fetchone() is not None
        assert conn.execute("SELECT document_id FROM ccvault_processed WHERE query_id=?", (_QID_BARE,)).fetchone()[0] == aw[0]
    finally:
        conn.close()


def test_reader_bytes_rawjson_and_list_toolresult(tmp_path):
    p = str(tmp_path / "ccvault.db")
    c = sqlite3.connect(p)
    c.executescript("""
        CREATE TABLE projects(id INTEGER PRIMARY KEY, path TEXT);
        CREATE TABLE sessions(id TEXT PRIMARY KEY, project_id INTEGER, started_at TEXT, turn_count INTEGER, source TEXT);
        CREATE TABLE turns(id TEXT PRIMARY KEY, session_id TEXT, parent_id TEXT, type TEXT, timestamp TEXT, content TEXT, raw_json BLOB);
        CREATE TABLE tool_uses(id INTEGER PRIMARY KEY, turn_id TEXT, session_id TEXT, tool_name TEXT, timestamp TEXT);
    """)
    c.execute("INSERT INTO sessions VALUES ('s', 1, '2026-09-01', 2, 'claude-code')")
    tu = {"message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "x", "name": "mcp__noospheric-orrery__get_entity", "input": {"name": "A"}}]}}
    tr = {"message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "x",
         "content": [{"type": "text", "text": "A (Concept) [entity:ent-x] [query:qry_" + "b" * 32 + "]"}]}]}}
    c.execute("INSERT INTO turns VALUES ('a','s',NULL,'assistant','t1','', ?)", (json.dumps(tu).encode("utf-8"),))
    c.execute("INSERT INTO turns VALUES ('b','s','a','user','t2','', ?)", (json.dumps(tr).encode("utf-8"),))
    c.commit(); c.close()
    conn = ccvault_reader.open_archive(p)
    try:
        segs = ccvault_reader.iter_segments(conn, "s")
        assert any("ent-x" in s["entity_ids"] and ("qry_" + "b" * 32) in s["query_ids"] for s in segs)
    finally:
        conn.close()


# ── robustness ──────────────────────────────────────────────────────────────────

def test_missing_primary_domain_falls_back(tmp_path, monkeypatch, test_db):
    async def classify_empty(relay, title, excerpt, existing_taxonomy, model):
        return {}
    monkeypatch.setattr(mod, "classify_document", classify_empty)
    monkeypatch.setattr(mod, "Relay", _FakeRelay)
    arcp = str(tmp_path / "ccvault.db"); _make_ccvault_db(arcp)
    cid = str(uuid.uuid4()); _seed_collection(test_db, cid)

    asyncio.run(mod.run_ingest_ccvault(_job(arcp, cid, test_db), test_db))  # must not raise

    conn = get_connection(test_db)
    try:
        doms = {r[0] for r in conn.execute("SELECT DISTINCT domain_path FROM document_domains")}
        assert mod._UNCLASSIFIED_DOMAIN in doms
        assert conn.execute("SELECT COUNT(*) FROM domains WHERE path IS NULL OR path=''").fetchone()[0] == 0
    finally:
        conn.close()


def test_empty_model_output_does_not_watermark(tmp_path, monkeypatch, test_db):
    monkeypatch.setattr(mod, "Relay", _EmptyRelay)
    async def fake_classify(relay, title, excerpt, existing_taxonomy, model):
        return {"primary_domain": "x"}
    monkeypatch.setattr(mod, "classify_document", fake_classify)
    arcp = str(tmp_path / "ccvault.db"); _make_ccvault_db(arcp)
    cid = str(uuid.uuid4()); _seed_collection(test_db, cid)

    asyncio.run(mod.run_ingest_ccvault(_job(arcp, cid, test_db), test_db))

    conn = get_connection(test_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
        seen = {r[0] for r in conn.execute("SELECT session_id FROM ccvault_sessions_seen")}
        assert "sess-1" not in seen   # empty MODEL output → retry
        assert "sess-2" in seen       # empty INPUT session → watermarked
    finally:
        conn.close()
