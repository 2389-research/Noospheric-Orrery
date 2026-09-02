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
