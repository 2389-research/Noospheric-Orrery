# ABOUTME: extract_batch writes co_occurs as a pure projection of entity_sources.
# ABOUTME: One row per pair, source_chunk NULL, weight = shared-chunk count.
"""Co-occurrence is a projection, not a log.

Spec 1 (incremental-source-sync) collapses the old two-representation scheme — an
aggregated `source_chunk` NULL row from extract_batch plus per-chunk rows from the
upload path — into a single representation: every valid `co_occurs` row is a pure
projection of `entity_sources`, written only by `recompute_cooccurrence`. Two entities
co-occur when they share a chunk; weight is the number of shared chunks; every projected
row carries `source_chunk = NULL`. A human-invalidated edge (a corrections decision) is
preserved and never revived by re-extraction.
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
    _seed(db_path, n=4)                       # alpha+beta co-occur in 4 distinct chunks

    await _run(db_path, monkeypatch)

    conn = get_connection(db_path)
    rows = _cooccurs(conn)
    conn.close()
    assert len(rows) == 1, f"expected one projected row, got {len(rows)}"
    assert rows[0]["weight"] == 4, "weight is the shared-chunk count across documents"
    assert rows[0]["source_chunk"] is None, "every projected row is source_chunk NULL"


async def test_a_legacy_per_chunk_row_is_reconciled_into_the_projection(tmp_path, monkeypatch):
    """Under the single-representation invariant there is no second row to protect. A
    legacy per-chunk row (non-null source_chunk) left by the old upload path is a VALID
    co_occurs row, so the recompute drops it and rebuilds the one projected row — no
    coexisting representations, no double-count."""
    db_path = str(tmp_path / "t.db")
    _seed(db_path, n=1)
    await _run(db_path, monkeypatch)          # alpha/beta now exist with stable ids
    conn = get_connection(db_path)
    a, b, _, _ = _cooccurs(conn)[0]
    # Plant a legacy per-chunk row for the same pair, as the old upload path would have.
    conn.execute("INSERT INTO relationships (id, from_entity, to_entity, type, weight, source_chunk) "
                 "VALUES (?, ?, ?, 'co_occurs', 9, 'some-chunk')", (str(uuid.uuid4()), a, b))
    conn.execute("UPDATE documents SET status = 'classified'")
    conn.commit()
    conn.close()
    await _run(db_path, monkeypatch)

    conn = get_connection(db_path)
    rows = _cooccurs(conn)
    conn.close()
    assert len(rows) == 1, "the legacy per-chunk row must be reconciled, not left alongside"
    assert rows[0]["source_chunk"] is None, "the surviving row is the projection"
    assert rows[0]["weight"] == 1, "weight is the shared-chunk count (one doc, one chunk)"


async def test_an_invalidated_edge_is_not_revived(tmp_path, monkeypatch):
    """A human-invalidated co_occurs row is a corrections decision. Re-extraction must
    never revive it: the projection skips any pair that still has an invalidated row, so
    no fresh valid edge is created for it."""
    db_path = str(tmp_path / "t.db")
    _seed(db_path, n=1)
    await _run(db_path, monkeypatch)
    conn = get_connection(db_path)
    # Invalidate the edge a human removed via corrections.
    conn.execute("UPDATE relationships SET invalid_at = CURRENT_TIMESTAMP WHERE type = 'co_occurs'")
    conn.execute("UPDATE documents SET status = 'classified'")
    conn.commit()
    conn.close()

    await _run(db_path, monkeypatch)

    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT weight, invalid_at FROM relationships WHERE type = 'co_occurs'").fetchall()
    conn.close()
    assert len(rows) == 1, "no fresh valid row — the invalidated edge stands alone"
    assert rows[0]["invalid_at"] is not None, "the surviving row is the invalidated one"
