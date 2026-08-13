# ABOUTME: extract_batch accumulates co-occurrence into one row per pair, not one per doc.
# ABOUTME: A pair in N docs used to leave N rows (all weight 1) — ~22% of the real table.
"""Co-occurrence is an aggregate, not a log.

The old write inserted a fresh `co_occurs` row for every document a pair appeared in, so
a pair seen in N documents left N rows of weight 1 — bloat, and wrong weight for every
reader that treats a row as an edge. Extraction now accumulates into the single
aggregated row (the one with `source_chunk` NULL), leaving the upload path's per-chunk
rows — which document deletion keys on — untouched, and never reviving an invalidated
edge by adding weight a reader can't see.
"""
import json
import uuid
from types import SimpleNamespace

import pytest

from src.db import get_connection, init_db


class FakeRelay:
    """One chunk -> two entities (alpha, beta) -> exactly one pair."""

    @classmethod
    def from_settings(cls, settings, **overrides):
        return cls()

    async def complete(self, model, max_tokens, messages, **kwargs):
        return SimpleNamespace(text=json.dumps(
            {"entities": [{"name": "alpha", "type": "Thing"}, {"name": "beta", "type": "Thing"}]}))


def _seed(db_path, n):
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO specs (id, domain_path, version, spec_content) VALUES ('s', NULL, 1, 'x')")
    for i in range(n):
        doc_id = str(uuid.uuid4())
        conn.execute("INSERT INTO documents (id, title, content, status, content_type) "
                     "VALUES (?, ?, 'body', 'classified', 'code_intent')", (doc_id, f"doc{i}"))
        conn.execute("INSERT INTO chunks (id, document_id, chunk_index, offset, length, text) "
                     "VALUES (?, ?, 0, 0, 5, ?)", (str(uuid.uuid4()), doc_id, f"CHUNK{i}"))
    conn.commit()
    conn.close()


async def _run(db_path, monkeypatch):
    import src.jobs.extract_batch as mod
    monkeypatch.setattr(mod, "Relay", FakeRelay)
    job = {"id": str(uuid.uuid4()), "config": json.dumps({"spec_id": "s", "scope": "code_intent"})}
    conn = get_connection(db_path)
    conn.execute("INSERT INTO jobs (id, type, target, status, config) "
                 "VALUES (?, 'extract_batch', 'code_intent', 'running', ?)", (job["id"], job["config"]))
    conn.commit()
    conn.close()
    await mod.run_extract_batch(job, db_path)


def _cooccurs(conn):
    return conn.execute(
        "SELECT from_entity, to_entity, weight, source_chunk FROM relationships "
        "WHERE type = 'co_occurs'").fetchall()


async def test_a_pair_in_many_docs_is_one_row_with_summed_weight(tmp_path, monkeypatch):
    db_path = str(tmp_path / "t.db")
    _seed(db_path, n=4)                       # alpha+beta co-occur in all 4 docs

    await _run(db_path, monkeypatch)

    conn = get_connection(db_path)
    rows = _cooccurs(conn)
    conn.close()
    assert len(rows) == 1, f"expected one aggregated row, got {len(rows)}"
    assert rows[0]["weight"] == 4, "weights were not accumulated across documents"
    assert rows[0]["source_chunk"] is None, "the aggregated code-intent edge is source_chunk NULL"


async def test_a_per_chunk_upload_row_is_left_untouched(tmp_path, monkeypatch):
    """The upload path writes per-chunk rows (non-null source_chunk) that document
    deletion depends on. Accumulation targets only the NULL-source_chunk row, so an
    existing per-chunk row for the same pair must survive, giving two rows that
    readers sum."""
    db_path = str(tmp_path / "t.db")
    _seed(db_path, n=1)
    # Extract once so alpha/beta exist with stable ids, then plant a per-chunk row.
    await _run(db_path, monkeypatch)
    conn = get_connection(db_path)
    a, b, _, _ = _cooccurs(conn)[0]
    conn.execute("INSERT INTO relationships (id, from_entity, to_entity, type, weight, source_chunk) "
                 "VALUES (?, ?, ?, 'co_occurs', 9, 'some-chunk')", (str(uuid.uuid4()), a, b))
    # Re-open the doc's scope and extract again: the aggregated row gains weight, the
    # per-chunk row does not.
    conn.execute("UPDATE documents SET status = 'classified'")
    conn.commit()
    conn.close()
    await _run(db_path, monkeypatch)

    conn = get_connection(db_path)
    rows = {r["source_chunk"]: r["weight"] for r in _cooccurs(conn)}
    conn.close()
    assert rows.get("some-chunk") == 9, "the per-chunk upload row was modified"
    assert rows.get(None) == 2, "the aggregated row did not accumulate (1 + 1)"


async def test_an_invalidated_edge_is_not_revived_by_accumulation(tmp_path, monkeypatch):
    """A human-invalidated co_occurs row is invisible to readers (they filter
    invalid_at IS NULL). Adding weight to it would silently drop that weight — so
    accumulation skips it and a fresh valid row is created, matching the old insert."""
    db_path = str(tmp_path / "t.db")
    _seed(db_path, n=1)
    await _run(db_path, monkeypatch)
    conn = get_connection(db_path)
    a, b, _, _ = _cooccurs(conn)[0]
    # Invalidate the aggregated row a human removed via corrections.
    conn.execute("UPDATE relationships SET invalid_at = CURRENT_TIMESTAMP WHERE type = 'co_occurs'")
    conn.execute("UPDATE documents SET status = 'classified'")
    conn.commit()
    conn.close()

    await _run(db_path, monkeypatch)

    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT weight, invalid_at FROM relationships WHERE type = 'co_occurs' "
        "ORDER BY invalid_at IS NULL").fetchall()
    conn.close()
    assert len(rows) == 2, "should be the invalidated row plus a fresh valid one"
    valid = [r for r in rows if r["invalid_at"] is None]
    assert len(valid) == 1 and valid[0]["weight"] == 1, "did not create a fresh valid edge"
    invalid = [r for r in rows if r["invalid_at"] is not None]
    assert invalid[0]["weight"] == 1, "weight was added to the invalidated (invisible) row"
