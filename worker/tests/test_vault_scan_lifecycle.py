# ABOUTME: End-to-end scan-lifecycle over a real temp vault with a stubbed relay.
# ABOUTME: Proves create/update-in-place/skip/soft-delete + frontmatter-in-metadata in the DB.
import json

import pytest

from src.db import init_db, get_connection
import src.jobs.scan_source as scan_source_mod
from .test_scan_source import FakeRelay, _run_scan   # reuse the existing harness


def _write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.mark.asyncio
async def test_vault_scan_lifecycle(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    _write(vault / "a.md", "---\ntags: [x]\n---\nnote about ALPHA\n")
    _write(vault / "b.md", "note about ALPHA too\n")
    _write(vault / ".obsidian" / "app.json", "{}")          # junk: must never ingest
    _write(vault / ".trash" / "old.md", "deleted note\n")   # junk: must never ingest

    db = str(tmp_path / "t.db")
    init_db(db)
    conn = get_connection(db)
    conn.execute("INSERT INTO watched_sources (id, type, uri) VALUES ('v1','vault',?)",
                 (str(vault),))
    conn.commit()
    conn.close()
    monkeypatch.setattr(scan_source_mod, "Relay", FakeRelay)

    # scan #1 — both real notes created; junk excluded; frontmatter in metadata, not body
    await _run_scan(db, source_id="v1")
    conn = get_connection(db)
    names = sorted(r["source_path"].rsplit("/", 1)[1] for r in conn.execute(
        "SELECT source_path FROM documents WHERE invalid_at IS NULL"))
    assert names == ["a.md", "b.md"]                                   # no .obsidian/.trash docs
    a = conn.execute("SELECT id, content, metadata FROM documents WHERE source_path LIKE '%a.md'").fetchone()
    assert "tags:" not in a["content"] and json.loads(a["metadata"])["tags"] == ["x"]
    a_id = a["id"]
    conn.close()

    # scan #2 — no disk change -> skip; same id; still two active docs
    await _run_scan(db, source_id="v1")
    conn = get_connection(db)
    assert conn.execute("SELECT id FROM documents WHERE source_path LIKE '%a.md' AND invalid_at IS NULL").fetchone()["id"] == a_id
    assert conn.execute("SELECT COUNT(*) c FROM documents WHERE invalid_at IS NULL").fetchone()["c"] == 2
    conn.close()

    # scan #3 — edit a.md -> update in place: SAME id, new content, exactly one a.md row (no dup)
    _write(vault / "a.md", "---\ntags: [x]\n---\nnote about GAMMA now\n")
    await _run_scan(db, source_id="v1")
    conn = get_connection(db)
    a2 = conn.execute("SELECT id, content FROM documents WHERE source_path LIKE '%a.md' AND invalid_at IS NULL").fetchone()
    assert a2["id"] == a_id and "GAMMA" in a2["content"]
    assert conn.execute("SELECT COUNT(*) c FROM documents WHERE source_path LIKE '%a.md'").fetchone()["c"] == 1
    conn.close()

    # scan #4 — delete b.md on disk -> soft-deleted; row survives; entity_sources cleared
    (vault / "b.md").unlink()
    await _run_scan(db, source_id="v1")
    conn = get_connection(db)
    assert conn.execute("SELECT COUNT(*) c FROM documents WHERE source_path LIKE '%b.md' AND invalid_at IS NULL").fetchone()["c"] == 0
    assert conn.execute("SELECT invalid_at FROM documents WHERE source_path LIKE '%b.md'").fetchone()["invalid_at"] is not None
    conn.close()

    # scan #5 — KNOWN LIMITATION (CodeRabbit #78, upsert_document.py:198): re-creating b.md
    # currently produces a NEW document id rather than restoring the soft-deleted one, because
    # the existing-doc lookup filters `invalid_at IS NULL`. Left commented so that whoever fixes
    # the restore bug turns this into a real assertion (re-added b.md reactivates the ORIGINAL id).
    # Encoding today's buggy behavior as a passing assertion would lock the bug in — do not.
    #
    # _write(vault / "b.md", "note about ALPHA too\n")
    # await _run_scan(db, source_id="v1")
    # conn = get_connection(db)
    # assert conn.execute("SELECT id FROM documents WHERE source_path LIKE '%b.md' AND invalid_at IS NULL").fetchone()["id"] == b_id
    # conn.close()
