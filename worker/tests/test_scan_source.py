# ABOUTME: scan_source applies the create/update/skip/delete decision table over a source.

import json
import uuid
from types import SimpleNamespace

import pytest

from src.db import init_db, get_connection
import src.jobs.scan_source as scan_source_mod


class FakeRelay:
    @classmethod
    def from_settings(cls, settings, **overrides):
        return cls()

    async def complete(self, model, max_tokens, messages, **kwargs):
        text = messages[0]["content"]
        ents = ([{"name": "gamma", "type": "Thing"}, {"name": "delta", "type": "Thing"}]
                if "GAMMA" in text else
                [{"name": "alpha", "type": "Thing"}, {"name": "beta", "type": "Thing"}])
        return SimpleNamespace(text=json.dumps({"entities": ents}))

    async def complete_structured(self, model, max_tokens, messages, **kwargs):
        return {"primary_domain": "techniques/test", "secondary_domains": [],
                "new_domains": [], "confidence": 0.9}


def _active_paths(conn):
    return {r["source_path"] for r in conn.execute(
        "SELECT source_path FROM documents WHERE invalid_at IS NULL")}


async def _run_scan(db, source_id="src1"):
    job = {"id": str(uuid.uuid4()), "type": "scan_source",
           "target": source_id, "config": json.dumps({"source_id": source_id})}
    await scan_source_mod.run_scan_source(job, db)


@pytest.mark.asyncio
async def test_scan_create_skip_and_delete(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    conn.execute("INSERT INTO watched_sources (id, type, uri) VALUES ('src1', 'fixture', '/x')")
    conn.commit(); conn.close()

    monkeypatch.setattr(scan_source_mod, "Relay", FakeRelay)

    # A mutable doc set the fixture featurizer reads each scan.
    docs = [("/x/a.md", "A", "note about ALPHA", True),
            ("/x/b.md", "B", "note about ALPHA too", True)]

    def fixture_featurizer(uri, config):
        yield from docs

    monkeypatch.setitem(scan_source_mod._FEATURIZERS, "fixture", fixture_featurizer)

    # 1. First scan -> both created.
    await _run_scan(db)
    conn = get_connection(db)
    assert _active_paths(conn) == {"/x/a.md", "/x/b.md"}
    ws = conn.execute("SELECT last_status, last_scanned_at FROM watched_sources WHERE id='src1'").fetchone()
    assert ws["last_status"] == "ok" and ws["last_scanned_at"] is not None
    b_id = conn.execute("SELECT id FROM documents WHERE source_path='/x/b.md'").fetchone()["id"]
    conn.close()

    # 2. Re-scan, no changes -> both skipped, still two active docs, same b id.
    await _run_scan(db)
    conn = get_connection(db)
    assert _active_paths(conn) == {"/x/a.md", "/x/b.md"}
    assert conn.execute("SELECT id FROM documents WHERE source_path='/x/b.md' AND invalid_at IS NULL").fetchone()["id"] == b_id
    conn.close()

    # 3. Drop b.md from the source -> re-scan soft-deletes it.
    docs.pop()  # remove b.md
    await _run_scan(db)
    conn = get_connection(db)
    assert _active_paths(conn) == {"/x/a.md"}
    b_row = conn.execute("SELECT invalid_at FROM documents WHERE id = ?", (b_id,)).fetchone()
    assert b_row["invalid_at"] is not None                     # soft-deleted, row survives
    assert conn.execute("SELECT COUNT(*) c FROM entity_sources WHERE document_id = ?", (b_id,)).fetchone()["c"] == 0
    # a.md's entities still project their edge; b's contribution is gone.
    edges = conn.execute("SELECT COUNT(*) c FROM relationships WHERE type='co_occurs' AND invalid_at IS NULL").fetchone()["c"]
    assert edges >= 1
    conn.close()
