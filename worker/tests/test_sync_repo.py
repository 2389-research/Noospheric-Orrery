# ABOUTME: Repo adapter E2E — codesum artifacts -> leaf/group/root docs through the spine.
# ABOUTME: Uses an injected fake summarizer; exercises create/update/skip/delete + emits gate.

import json
import uuid
from types import SimpleNamespace

import pytest

from src.db import init_db, get_connection, recompute_cooccurrence
import src.jobs.scan_source as scan_source_mod
import src.jobs.sync_repo as sync_repo_mod


class FakeRelay:
    @classmethod
    def from_settings(cls, settings, **kw):
        return cls()

    async def complete(self, model, max_tokens, messages, **kw):
        text = messages[0]["content"]
        ents = [{"name": n, "type": "Concept"}
                for m, n in (("ALPHA", "alpha"), ("BETA", "beta"),
                             ("GAMMA", "gamma"), ("DELTA", "delta")) if m in text]
        return SimpleNamespace(text=json.dumps({"entities": ents}))


async def _fake_classify(relay, title, excerpt, existing_taxonomy, model):
    return {"primary_domain": "code/repo", "secondary_domains": [], "new_domains": [], "confidence": 0.9}


def _valid_edges(conn):
    out = []
    for r in conn.execute(
        "SELECT ea.canonical_name a, eb.canonical_name b, r.weight w FROM relationships r "
        "JOIN entities ea ON ea.id = r.from_entity JOIN entities eb ON eb.id = r.to_entity "
        "WHERE r.type='co_occurs' AND r.invalid_at IS NULL"):
        pair = tuple(sorted((r["a"], r["b"])))
        out.append((pair[0], pair[1], r["w"]))
    return sorted(out)


async def _scan(db):
    job = {"id": str(uuid.uuid4()), "type": "scan_source",
           "target": "src1", "config": json.dumps({"source_id": "src1"})}
    await scan_source_mod.run_scan_source(job, db)


@pytest.mark.asyncio
async def test_repo_sync_hierarchy_and_change_detection(tmp_path, monkeypatch):
    repo = tmp_path / "myrepo"; repo.mkdir()
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    conn.execute("INSERT INTO watched_sources (id, type, uri) VALUES ('src1', 'repo', ?)", (str(repo),))
    conn.commit(); conn.close()

    # Fake codesum: a mutable artifact list (root + module + two leaves).
    artifacts = [
        {"repo": "myrepo", "path": ".", "level": "repo", "parent_path": None, "intent": "root ALPHA BETA GAMMA"},
        {"repo": "myrepo", "path": "mod", "level": "module", "parent_path": ".", "intent": "module ALPHA BETA"},
        {"repo": "myrepo", "path": "mod/a.py", "level": "file", "parent_path": "mod", "intent": "file a ALPHA BETA"},
        {"repo": "myrepo", "path": "mod/b.py", "level": "file", "parent_path": "mod", "intent": "file b BETA GAMMA"},
    ]
    monkeypatch.setattr(scan_source_mod, "Relay", FakeRelay)
    monkeypatch.setattr(sync_repo_mod, "make_summarize_fn", lambda relay, model: (lambda *a, **k: ""))
    monkeypatch.setattr(sync_repo_mod, "summarize_repo", lambda root, fn, name: list(artifacts))
    monkeypatch.setattr(sync_repo_mod, "classify_document", _fake_classify)

    # 1. First scan -> 4 docs; roles + emits gate correct; only leaf edges.
    await _scan(db)
    conn = get_connection(db)
    roles = {r["role"]: r["emits_cooccurrence"] for r in conn.execute(
        "SELECT role, emits_cooccurrence FROM document_collections")}
    assert roles == {"root": 0, "group": 0, "leaf": 1}
    assert conn.execute("SELECT COUNT(*) c FROM document_collections WHERE role='leaf'").fetchone()["c"] == 2
    # every repo doc filed under the repo domain, none classified per-doc
    assert {r["domain_path"] for r in conn.execute("SELECT DISTINCT domain_path FROM document_domains")} == {"code/repo"}
    # leaf edges only; module/root (ALPHA BETA / ALPHA BETA GAMMA) inject no hub edges
    assert _valid_edges(conn) == [("alpha", "beta", 1), ("beta", "gamma", 1)]
    assert _valid_edges(conn) == _from_scratch(conn)
    conn.close()

    # 2. Change b.py's summary -> re-scan -> b.py updated, others skipped.
    artifacts[3]["intent"] = "file b GAMMA DELTA"
    await _scan(db)
    conn = get_connection(db)
    assert _valid_edges(conn) == [("alpha", "beta", 1), ("delta", "gamma", 1)]
    assert _valid_edges(conn) == _from_scratch(conn)
    conn.close()

    # 3. Drop b.py from the tree -> re-scan -> its leaf soft-deleted, edge retracted.
    artifacts.pop()   # remove b.py
    await _scan(db)
    conn = get_connection(db)
    assert _valid_edges(conn) == [("alpha", "beta", 1)]
    b_path = str(repo / "mod/b.py")
    assert conn.execute("SELECT invalid_at FROM documents WHERE source_path=?", (b_path,)).fetchone()["invalid_at"] is not None
    conn.close()

    # 4. No change -> everything skipped, graph identical.
    conn = get_connection(db); before = _valid_edges(conn); conn.close()
    await _scan(db)
    conn = get_connection(db)
    assert _valid_edges(conn) == before == [("alpha", "beta", 1)]
    conn.close()


def _from_scratch(conn):
    active = [r["id"] for r in conn.execute("SELECT id FROM entities WHERE invalid_at IS NULL")]
    conn.execute("DELETE FROM relationships WHERE type='co_occurs' AND invalid_at IS NULL")
    recompute_cooccurrence(conn, active); conn.commit()
    return _valid_edges(conn)


@pytest.mark.asyncio
async def test_scan_short_circuits_when_head_sha_unchanged(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir()
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    conn.execute("INSERT INTO watched_sources (id, type, uri) VALUES ('src1', 'repo', ?)", (str(repo),))
    conn.commit(); conn.close()

    calls = {"n": 0}
    def fake_summarize(root, fn, name):
        calls["n"] += 1
        return [{"repo": "r", "path": "a.py", "level": "file", "parent_path": ".", "intent": "file ALPHA BETA"}]

    monkeypatch.setattr(scan_source_mod, "Relay", FakeRelay)
    monkeypatch.setattr(sync_repo_mod, "make_summarize_fn", lambda relay, model: (lambda *a, **k: ""))
    monkeypatch.setattr(sync_repo_mod, "summarize_repo", fake_summarize)
    monkeypatch.setattr(sync_repo_mod, "classify_document", _fake_classify)

    sha = {"v": "sha-1"}
    monkeypatch.setattr(sync_repo_mod, "_git_head_sha", lambda p: sha["v"])

    # First scan: full run, codesum called once, sha recorded on the collection.
    await _scan(db)
    assert calls["n"] == 1
    conn = get_connection(db)
    assert conn.execute("SELECT commit_sha FROM collections").fetchone()["commit_sha"] == "sha-1"
    conn.close()

    # HEAD unchanged -> short-circuit: codesum NOT called again.
    await _scan(db)
    assert calls["n"] == 1

    # HEAD moves -> full re-summarize.
    sha["v"] = "sha-2"
    await _scan(db)
    assert calls["n"] == 2
    conn = get_connection(db)
    assert conn.execute("SELECT commit_sha FROM collections").fetchone()["commit_sha"] == "sha-2"
    conn.close()


@pytest.mark.asyncio
async def test_non_git_source_never_short_circuits(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir()
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    conn.execute("INSERT INTO watched_sources (id, type, uri) VALUES ('src1', 'repo', ?)", (str(repo),))
    conn.commit(); conn.close()

    calls = {"n": 0}
    def fake_summarize(root, fn, name):
        calls["n"] += 1
        return [{"repo": "r", "path": "a.py", "level": "file", "parent_path": ".", "intent": "file ALPHA BETA"}]

    monkeypatch.setattr(scan_source_mod, "Relay", FakeRelay)
    monkeypatch.setattr(sync_repo_mod, "make_summarize_fn", lambda relay, model: (lambda *a, **k: ""))
    monkeypatch.setattr(sync_repo_mod, "summarize_repo", fake_summarize)
    monkeypatch.setattr(sync_repo_mod, "classify_document", _fake_classify)
    monkeypatch.setattr(sync_repo_mod, "_git_head_sha", lambda p: None)   # not a git repo

    await _scan(db)
    await _scan(db)
    assert calls["n"] == 2   # no sha -> always re-summarizes
