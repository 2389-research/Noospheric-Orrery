# ABOUTME: Flow A of ccvault ingestion (docs/ccvault-ingestion.md) — sessions summarized into
# ABOUTME: neutral agent_report docs, per-session dedup ledger, session-scoped extract_batch.

import asyncio
import json
import sqlite3
import uuid

import pytest

import src.jobs.ingest_ccvault as mod
from src.jobs import ccvault_reader
from src.db import get_connection


# ── build a tiny ccvault archive ──────────────────────────────────────────────

def _make_ccvault_db(path):
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE projects (id INTEGER PRIMARY KEY, path TEXT);
        CREATE TABLE sessions (id TEXT PRIMARY KEY, project_id INTEGER, started_at TEXT,
                               turn_count INTEGER, source TEXT);
        CREATE TABLE turns (id TEXT PRIMARY KEY, session_id TEXT, parent_id TEXT, type TEXT,
                            timestamp TEXT, content TEXT, raw_json BLOB);
        CREATE TABLE tool_uses (id INTEGER PRIMARY KEY, turn_id TEXT, session_id TEXT,
                                tool_name TEXT, timestamp TEXT);
    """)
    c.execute("INSERT INTO projects (id, path) VALUES (1, '/home/u/proj-alpha')")
    # session S1: real user/assistant content -> gets summarized
    c.execute("INSERT INTO sessions VALUES ('sess-1', 1, '2026-09-01 10:00:00', 4, 'claude-code')")
    c.execute("INSERT INTO turns VALUES ('t1','sess-1',NULL,'user','2026-09-01 10:00:01','Investigate the auth module', NULL)")
    c.execute("INSERT INTO turns VALUES ('t2','sess-1','t1','assistant','2026-09-01 10:00:02','Looked at auth.py and found the token check', NULL)")
    c.execute("INSERT INTO tool_uses VALUES (1,'t2','sess-1','mcp__noospheric-orrery__search_knowledge_graph','2026-09-01 10:00:02')")
    # session S2: only system/tool turns, no user/assistant content -> no transcript -> marked seen, no doc
    c.execute("INSERT INTO sessions VALUES ('sess-2', 1, '2026-09-01 11:00:00', 2, 'claude-code')")
    c.execute("INSERT INTO turns VALUES ('t3','sess-2',NULL,'system','2026-09-01 11:00:01','boot', NULL)")
    # session S3: a codex session -> excluded by the default claude-code source filter
    c.execute("INSERT INTO sessions VALUES ('sess-3', 1, '2026-09-01 12:00:00', 2, 'codex')")
    c.execute("INSERT INTO turns VALUES ('t4','sess-3',NULL,'user','2026-09-01 12:00:01','hi from codex', NULL)")
    c.commit()
    c.close()


class _Resp:
    def __init__(self, text): self.text = text


class _FakeRelay:
    async def complete(self, model, max_tokens, messages):
        return _Resp("The session investigated the auth module and reviewed the token check in auth.py.")

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
        "VALUES (?, 'ccvault', 'ccvault', '/tmp/cc', 'ccvault', 'agent_report', 0)",
        (collection_id,))
    conn.commit()
    conn.close()


def _job(archive_path, collection_id, db_path=None):
    """Build the job dict; if db_path is given, also insert the jobs row (as the route
    would) so the job's own `UPDATE jobs SET result=…` has a row to write."""
    job = {"id": str(uuid.uuid4()), "type": "ingest_ccvault", "target": collection_id,
           "config": json.dumps({"archive_path": archive_path, "collection_id": collection_id,
                                 "spec_id": "spec-x"})}
    if db_path:
        conn = get_connection(db_path)
        conn.execute("INSERT INTO jobs (id, type, target, status, config) VALUES (?, ?, ?, 'running', ?)",
                     (job["id"], job["type"], job["target"], job["config"]))
        conn.commit()
        conn.close()
    return job


# ── reader ────────────────────────────────────────────────────────────────────

def test_reader_lists_only_claude_code_and_reads_transcript(tmp_path):
    arcp = str(tmp_path / "ccvault.db")
    _make_ccvault_db(arcp)
    conn = ccvault_reader.open_archive(arcp)
    try:
        sessions = ccvault_reader.list_sessions(conn)  # default source=claude-code
        ids = [s["session_id"] for s in sessions]
        assert ids == ["sess-1", "sess-2"]  # codex sess-3 excluded, chronological
        assert ccvault_reader.list_sessions(conn, source="")  # '' takes all
        t = ccvault_reader.session_transcript(conn, "sess-1")
        assert "auth module" in t and "[user]" in t and "[assistant]" in t
        assert ccvault_reader.session_transcript(conn, "sess-2") == ""  # no user/assistant turns
        assert ccvault_reader.uses_orrery_graph(conn, "sess-1") is True
        assert ccvault_reader.uses_orrery_graph(conn, "sess-2") is False
    finally:
        conn.close()


def test_reader_accepts_directory(tmp_path):
    _make_ccvault_db(str(tmp_path / "ccvault.db"))
    conn = ccvault_reader.open_archive(str(tmp_path))  # dir containing ccvault.db
    try:
        assert len(ccvault_reader.list_sessions(conn)) == 2
    finally:
        conn.close()


# ── Flow A end to end ─────────────────────────────────────────────────────────

def test_flow_a_creates_agent_report_doc_and_enqueues_extract(tmp_path, monkeypatch, test_db):
    _stub(monkeypatch)
    arcp = str(tmp_path / "ccvault.db")
    _make_ccvault_db(arcp)
    cid = str(uuid.uuid4())
    _seed_collection(test_db, cid)

    asyncio.run(mod.run_ingest_ccvault(_job(arcp, cid), test_db))

    conn = get_connection(test_db)
    try:
        docs = conn.execute(
            "SELECT id, content_type, status, silo_id FROM documents").fetchall()
        assert len(docs) == 1, "only sess-1 (with content) becomes a doc"
        d = docs[0]
        assert d["content_type"] == "session_intent"
        assert d["status"] == "classified"
        assert d["silo_id"] == cid, "silo_id set explicitly to the ccvault collection"
        # a chunk exists for extraction
        assert conn.execute("SELECT COUNT(*) FROM chunks WHERE document_id = ?", (d["id"],)).fetchone()[0] == 1
        # doc is linked to the collection
        assert conn.execute("SELECT COUNT(*) FROM document_collections WHERE document_id = ?",
                            (d["id"],)).fetchone()[0] == 1
        # silo resolves to agent_report (co-occurrence gated)
        kind = conn.execute("SELECT kind FROM silo_kind WHERE silo_id = ?", (cid,)).fetchone()[0]
        assert kind == "agent_report"
        # BOTH sessions marked seen (sess-2 was empty but still watermarked)
        seen = {r[0] for r in conn.execute("SELECT session_id FROM ccvault_sessions_seen")}
        assert seen == {"sess-1", "sess-2"}
        # a session-scoped extract_batch is queued
        eb = conn.execute("SELECT config FROM jobs WHERE type = 'extract_batch'").fetchone()
        assert eb and json.loads(eb[0])["scope"] == "session_intent"
        # Flow B untouched
        assert conn.execute("SELECT COUNT(*) FROM ccvault_processed").fetchone()[0] == 0
    finally:
        conn.close()


# ── Flow B (active-work extraction) ───────────────────────────────────────────

_QID = "qry_" + "a" * 32


def _make_ccvault_db_tags(path, entity_tag="ent-auth", query_id=_QID):
    """One graph-using session whose raw_json carries the #93 tags in a tool_result."""
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE projects (id INTEGER PRIMARY KEY, path TEXT);
        CREATE TABLE sessions (id TEXT PRIMARY KEY, project_id INTEGER, started_at TEXT,
                               turn_count INTEGER, source TEXT);
        CREATE TABLE turns (id TEXT PRIMARY KEY, session_id TEXT, parent_id TEXT, type TEXT,
                            timestamp TEXT, content TEXT, raw_json BLOB);
        CREATE TABLE tool_uses (id INTEGER PRIMARY KEY, turn_id TEXT, session_id TEXT,
                                tool_name TEXT, timestamp TEXT);
    """)
    c.execute("INSERT INTO projects (id, path) VALUES (1, '/home/u/proj-auth')")
    c.execute("INSERT INTO sessions VALUES ('sess-g', 1, '2026-09-01 10:00:00', 3, 'claude-code')")
    tu = {"message": {"role": "assistant", "content": [
        {"type": "text", "text": "Let me look up Auth."},
        {"type": "tool_use", "id": "tu1", "name": "mcp__noospheric-orrery__get_entity",
         "input": {"name": "Auth"}}]}}
    tr = {"message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "tu1",
         "content": f"Auth (Concept) [entity:{entity_tag}] [query:{query_id}]\nSources: 1 mention"}]}}
    syn = {"message": {"role": "assistant", "content": [
        {"type": "text", "text": "Auth relies on token checks in auth.py."}]}}
    c.execute("INSERT INTO turns VALUES ('g1','sess-g',NULL,'assistant','2026-09-01 10:00:01','Let me look up Auth.', ?)", (json.dumps(tu),))
    c.execute("INSERT INTO turns VALUES ('g2','sess-g','g1','user','2026-09-01 10:00:02','[tool result]', ?)", (json.dumps(tr),))
    c.execute("INSERT INTO turns VALUES ('g3','sess-g','g2','assistant','2026-09-01 10:00:03','Auth relies on token checks in auth.py.', ?)", (json.dumps(syn),))
    c.execute("INSERT INTO tool_uses VALUES (1,'g1','sess-g','mcp__noospheric-orrery__get_entity','2026-09-01 10:00:01')")
    c.commit()
    c.close()


def _seed_entity(db_path, eid="ent-auth", name="Auth"):
    conn = get_connection(db_path)
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES (?, ?, 'Concept')", (eid, name))
    conn.commit()
    conn.close()


def test_reader_graph_work_parses_tags_and_synthesis(tmp_path):
    arcp = str(tmp_path / "ccvault.db")
    _make_ccvault_db_tags(arcp)
    conn = ccvault_reader.open_archive(arcp)
    try:
        w = ccvault_reader.graph_work(conn, "sess-g")
        assert w["query_ids"] == [_QID]
        assert w["entity_ids"] == {"ent-auth"}
        assert ("get_entity", {"name": "Auth"}) in w["tool_calls"]
        assert "token checks" in w["synthesis"]
    finally:
        conn.close()


def test_flow_b_creates_active_work_doc_linked_to_entity(tmp_path, monkeypatch, test_db):
    _stub(monkeypatch)
    arcp = str(tmp_path / "ccvault.db")
    _make_ccvault_db_tags(arcp)
    cid = str(uuid.uuid4())
    _seed_collection(test_db, cid)
    _seed_entity(test_db, "ent-auth", "Auth")   # the entity resolves in this clone

    asyncio.run(mod.run_ingest_ccvault(_job(arcp, cid, test_db), test_db))

    conn = get_connection(test_db)
    try:
        aw = conn.execute(
            "SELECT id, status, silo_id FROM documents WHERE content_type = 'active_work'").fetchall()
        assert len(aw) == 1
        doc = aw[0]
        assert doc["status"] == "extracted" and doc["silo_id"] == cid
        # anchored to the entity by a chunk-less entity_sources row (the direct link)
        link = conn.execute(
            "SELECT chunk_id, extraction_pass FROM entity_sources WHERE entity_id = 'ent-auth' "
            "AND document_id = ?", (doc["id"],)).fetchone()
        assert link is not None and link["chunk_id"] is None and link["extraction_pass"] == "ccvault_flowb"
        # NO chunk for an active_work doc (entity-channel recall only)
        assert conn.execute("SELECT COUNT(*) FROM chunks WHERE document_id = ?", (doc["id"],)).fetchone()[0] == 0
        # the query_id ledger points at the doc
        pr = conn.execute("SELECT document_id FROM ccvault_processed WHERE query_id = ?", (_QID,)).fetchone()
        assert pr is not None and pr[0] == doc["id"]
        # retrieval loop: the entity now lists this active-work doc among its sources
        got = conn.execute(
            "SELECT d.id FROM entity_sources es JOIN documents d ON d.id = es.document_id "
            "WHERE es.entity_id = 'ent-auth' AND d.invalid_at IS NULL AND d.content_type = 'active_work'"
        ).fetchone()
        assert got and got[0] == doc["id"]
    finally:
        conn.close()


def test_flow_b_unanchored_when_entity_absent(tmp_path, monkeypatch, test_db):
    """Graph-work seen but no tagged entity resolves in this workspace → no active_work doc,
    but the query_id is still recorded (document_id NULL) so re-ingest won't reprocess it."""
    _stub(monkeypatch)
    arcp = str(tmp_path / "ccvault.db")
    _make_ccvault_db_tags(arcp)
    cid = str(uuid.uuid4())
    _seed_collection(test_db, cid)
    # NOTE: no _seed_entity — ent-auth does not exist here

    asyncio.run(mod.run_ingest_ccvault(_job(arcp, cid, test_db), test_db))

    conn = get_connection(test_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM documents WHERE content_type='active_work'").fetchone()[0] == 0
        pr = conn.execute("SELECT document_id FROM ccvault_processed WHERE query_id = ?", (_QID,)).fetchone()
        assert pr is not None and pr[0] is None   # seen, unanchored
    finally:
        conn.close()


def test_flow_b_reingest_is_noop(tmp_path, monkeypatch, test_db):
    _stub(monkeypatch)
    arcp = str(tmp_path / "ccvault.db")
    _make_ccvault_db_tags(arcp)
    cid = str(uuid.uuid4())
    _seed_collection(test_db, cid)
    _seed_entity(test_db, "ent-auth", "Auth")

    asyncio.run(mod.run_ingest_ccvault(_job(arcp, cid, test_db), test_db))
    job2 = _job(arcp, cid, test_db)
    asyncio.run(mod.run_ingest_ccvault(job2, test_db))

    conn = get_connection(test_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM documents WHERE content_type='active_work'").fetchone()[0] == 1
        res = json.loads(conn.execute("SELECT result FROM jobs WHERE id = ?", (job2["id"],)).fetchone()[0])
        assert res["active_work_docs"] == 0   # second pass: query_id already processed
    finally:
        conn.close()


def test_flow_a_reingest_is_noop(tmp_path, monkeypatch, test_db):
    _stub(monkeypatch)
    arcp = str(tmp_path / "ccvault.db")
    _make_ccvault_db(arcp)
    cid = str(uuid.uuid4())
    _seed_collection(test_db, cid)

    asyncio.run(mod.run_ingest_ccvault(_job(arcp, cid, test_db), test_db))
    job2 = _job(arcp, cid, test_db)
    asyncio.run(mod.run_ingest_ccvault(job2, test_db))  # second pass

    conn = get_connection(test_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1, "no duplicate doc"
        # second run summarized nothing new
        last = conn.execute("SELECT result FROM jobs WHERE id = ?", (job2["id"],)).fetchone()
        assert json.loads(last[0])["sessions_summarized"] == 0
        assert json.loads(last[0])["sessions_skipped_seen"] == 2
    finally:
        conn.close()
