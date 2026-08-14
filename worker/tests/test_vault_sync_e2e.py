# ABOUTME: End-to-end vault sync — register a vault, scan it, edit / delete / re-scan.
# ABOUTME: The acceptance test for Spec 1: new/changed/deleted notes update the graph in place.

import json
import uuid
from types import SimpleNamespace

import pytest

from src.db import init_db, get_connection, recompute_cooccurrence
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
        return {"primary_domain": "notes/test", "secondary_domains": [],
                "new_domains": [], "confidence": 0.9}


def _valid_edges(conn):
    out = []
    for r in conn.execute(
        "SELECT ea.canonical_name a, eb.canonical_name b, r.weight w FROM relationships r "
        "JOIN entities ea ON ea.id = r.from_entity JOIN entities eb ON eb.id = r.to_entity "
        "WHERE r.type='co_occurs' AND r.invalid_at IS NULL"):
        pair = tuple(sorted((r["a"], r["b"])))
        out.append((pair[0], pair[1], r["w"]))
    return sorted(out)


def _active_titles(conn):
    return {r["title"] for r in conn.execute(
        "SELECT title FROM documents WHERE invalid_at IS NULL")}


def _from_scratch(conn):
    active = [r["id"] for r in conn.execute("SELECT id FROM entities WHERE invalid_at IS NULL")]
    conn.execute("DELETE FROM relationships WHERE type='co_occurs' AND invalid_at IS NULL")
    recompute_cooccurrence(conn, active)
    conn.commit()
    return _valid_edges(conn)


async def _scan(db):
    job = {"id": str(uuid.uuid4()), "type": "scan_source",
           "target": "src1", "config": json.dumps({"source_id": "src1"})}
    await scan_source_mod.run_scan_source(job, db)


@pytest.mark.asyncio
async def test_vault_sync_create_update_delete_skip(tmp_path, monkeypatch):
    vault = tmp_path / "vault"; vault.mkdir()
    note1 = vault / "note1.md"; note1.write_text("a note about ALPHA topics")
    note2 = vault / "note2.md"; note2.write_text("another note about ALPHA topics")

    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    conn.execute("INSERT INTO watched_sources (id, type, uri) VALUES ('src1', 'vault', ?)", (str(vault),))
    conn.commit(); conn.close()

    monkeypatch.setattr(scan_source_mod, "Relay", FakeRelay)

    # 1. First scan -> both notes ingested; alpha-beta co-occur in 2 chunks (both notes).
    await _scan(db)
    conn = get_connection(db)
    assert _active_titles(conn) == {"note1", "note2"}
    assert _valid_edges(conn) == [("alpha", "beta", 2)]
    assert _valid_edges(conn) == _from_scratch(conn)
    conn.close()

    # 2. Edit note2 -> re-scan -> updated in place; stale entities retracted.
    note2.write_text("another note about GAMMA topics")
    await _scan(db)
    conn = get_connection(db)
    assert _active_titles(conn) == {"note1", "note2"}
    # note1: alpha-beta (1 chunk); note2: gamma-delta (1 chunk)
    assert _valid_edges(conn) == [("alpha", "beta", 1), ("delta", "gamma", 1)]
    edges = _valid_edges(conn)
    assert edges == _from_scratch(conn)
    conn.close()

    # 3. Delete note2's file -> re-scan -> soft-deleted, its edges retracted.
    note2.unlink()
    await _scan(db)
    conn = get_connection(db)
    assert _active_titles(conn) == {"note1"}
    assert _valid_edges(conn) == [("alpha", "beta", 1)]
    # gamma/delta orphaned -> soft-deleted
    assert conn.execute("SELECT COUNT(*) c FROM entities WHERE canonical_name IN ('gamma','delta') "
                        "AND invalid_at IS NULL").fetchone()["c"] == 0
    conn.close()

    # 4. Re-scan with no changes -> all skipped, graph unchanged.
    before = None
    conn = get_connection(db); before = _valid_edges(conn); conn.close()
    await _scan(db)
    conn = get_connection(db)
    assert _valid_edges(conn) == before == [("alpha", "beta", 1)]
    assert _active_titles(conn) == {"note1"}
    conn.close()
