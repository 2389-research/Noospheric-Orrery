# ABOUTME: Tests for incremental entity normalization (embed-only-new + new-vs-all matmul).
# ABOUTME: Locks in: only new entities embedded, new-vs-old & new-vs-new merges, no re-adjudication.

import uuid

import numpy as np
import pytest
from unittest.mock import patch

import src.normalizer as norm
from src.db import get_connection


def _n(v):
    v = np.array(v, dtype=np.float32)
    return v / np.linalg.norm(v)


# Controlled 4-d unit vectors. dot(base, ·): auto≈0.95 (≥0.85), review≈0.78 (0.70-0.85), diff=0.
VEC = {
    "base": _n([1, 0, 0, 0]),
    "auto": _n([0.95, 0.32, 0, 0]),
    "review": _n([0.78, 0.63, 0, 0]),
    "diff": _n([0, 1, 0, 0]),
}


def _add_entity(conn, eid, name, etype="concept", sources=1, stored_vec=None):
    """Insert an entity. stored_vec present → 'old' (pre-embedded); absent → 'new'."""
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES (?, ?, ?)", (eid, name, etype))
    for _ in range(sources):
        conn.execute("INSERT INTO entity_sources (entity_id) VALUES (?)", (eid,))
    if stored_vec is not None:
        conn.execute(
            "INSERT INTO entity_embeddings (entity_id, embedding) VALUES (?, ?)",
            (eid, np.asarray(stored_vec, dtype=np.float32).tobytes()),
        )
    conn.commit()


def _embedder(mapping, calls=None):
    """Fake embed_entities: returns VEC by name; optionally records call name-lists."""
    def _embed(names):
        if calls is not None:
            calls.append(list(names))
        return np.array([mapping[n] for n in names], dtype=np.float32)
    return _embed


def _count(conn):
    return conn.execute("SELECT COUNT(*) FROM entities WHERE invalid_at IS NULL").fetchone()[0]


def test_noop_when_nothing_new(test_db):
    conn = get_connection(test_db)
    _add_entity(conn, "a", "alpha", stored_vec=VEC["base"])
    _add_entity(conn, "b", "beta", stored_vec=VEC["diff"])
    calls = []
    with patch.object(norm, "embed_entities", _embedder({}, calls)):
        res = norm.run_batch_normalization(conn)
    assert calls == []  # embed never called — nothing new
    assert res["embedding_merges"] == 0 and res["queued_for_review"] == 0
    assert _count(conn) == 2
    conn.close()


def test_only_new_entities_are_embedded(test_db):
    conn = get_connection(test_db)
    _add_entity(conn, "a", "alpha", stored_vec=VEC["base"])   # old
    _add_entity(conn, "b", "beta", stored_vec=VEC["diff"])    # old
    _add_entity(conn, "c", "gamma")                            # new (no stored vec)
    calls = []
    with patch.object(norm, "embed_entities", _embedder({"gamma": VEC["review"]}, calls)):
        norm.run_batch_normalization(conn)
    assert calls == [["gamma"]]  # embedded only the new one
    conn.close()


def test_new_vs_old_auto_merge_keeps_higher_source_count(test_db):
    conn = get_connection(test_db)
    _add_entity(conn, "old", "http client", sources=3, stored_vec=VEC["base"])
    _add_entity(conn, "new", "httpclient", sources=1)  # new, near-duplicate
    with patch.object(norm, "embed_entities", _embedder({"httpclient": VEC["auto"]})):
        res = norm.run_batch_normalization(conn)
    assert res["embedding_merges"] == 1
    assert _count(conn) == 1
    # survivor is the higher-source-count OLD entity
    assert conn.execute("SELECT id FROM entities WHERE invalid_at IS NULL").fetchone()[0] == "old"
    assert conn.execute("SELECT to_entity_id FROM merge_map WHERE from_name = ?", ("httpclient",)).fetchone()[0] == "old"
    conn.close()


def test_new_vs_new_auto_merge(test_db):
    conn = get_connection(test_db)
    _add_entity(conn, "x", "cli tool")   # both new
    _add_entity(conn, "y", "cli-tool")
    with patch.object(norm, "embed_entities", _embedder({"cli tool": VEC["base"], "cli-tool": VEC["auto"]})):
        res = norm.run_batch_normalization(conn)
    assert res["embedding_merges"] == 1
    assert _count(conn) == 1
    conn.close()


def test_type_scoping_prevents_cross_type_merge(test_db):
    conn = get_connection(test_db)
    _add_entity(conn, "a", "cache", etype="component", stored_vec=VEC["base"])
    _add_entity(conn, "b", "cache", etype="technique")  # identical vector, different type
    with patch.object(norm, "embed_entities", _embedder({"cache": VEC["auto"]})):
        res = norm.run_batch_normalization(conn)
    assert res["embedding_merges"] == 0
    assert _count(conn) == 2
    conn.close()


def test_review_range_queued_and_not_readjudicated(test_db):
    conn = get_connection(test_db)
    _add_entity(conn, "a", "oauth", sources=2, stored_vec=VEC["base"])
    _add_entity(conn, "b", "oauth2")  # new, review-range similar
    with patch.object(norm, "embed_entities", _embedder({"oauth2": VEC["review"]})):
        res1 = norm.run_batch_normalization(conn)
    assert res1["queued_for_review"] == 1
    assert conn.execute("SELECT COUNT(*) FROM normalization_review_queue").fetchone()[0] == 1

    # Resolve it as keep-distinct, then re-run: b is now 'old' (embedded), so the
    # pair is never re-generated — no re-adjudication, no duplicate row.
    conn.execute("UPDATE normalization_review_queue SET status = 'kept'")
    conn.commit()
    calls = []
    with patch.object(norm, "embed_entities", _embedder({}, calls)):
        res2 = norm.run_batch_normalization(conn)
    assert calls == []
    assert res2["queued_for_review"] == 0
    assert conn.execute("SELECT COUNT(*) FROM normalization_review_queue").fetchone()[0] == 1
    conn.close()


def test_resolved_pair_not_requeued_even_if_partner_is_new(test_db):
    conn = get_connection(test_db)
    _add_entity(conn, "a", "oauth", sources=2, stored_vec=VEC["base"])
    _add_entity(conn, "b", "oauth2")  # new
    # A human already decided this pair as keep-distinct in a prior life.
    conn.execute(
        "INSERT INTO normalization_review_queue (id, entity_a_id, entity_a_name, entity_b_id, entity_b_name, similarity, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'kept')",
        (str(uuid.uuid4()), "a", "oauth", "b", "oauth2", 0.78),
    )
    conn.commit()
    with patch.object(norm, "embed_entities", _embedder({"oauth2": VEC["review"]})):
        res = norm.run_batch_normalization(conn)
    assert res["queued_for_review"] == 0  # dedup against ANY status, not just pending
    assert conn.execute("SELECT COUNT(*) FROM normalization_review_queue").fetchone()[0] == 1
    conn.close()


def test_plural_collapse_new_entity(test_db):
    conn = get_connection(test_db)
    _add_entity(conn, "sing", "agent", stored_vec=VEC["base"])
    _add_entity(conn, "plur", "agents")  # new plural of an existing singular
    with patch.object(norm, "embed_entities", _embedder({"agents": VEC["diff"]})):
        res = norm.run_batch_normalization(conn)
    assert res["plural_merges"] == 1
    assert _count(conn) == 1
    assert conn.execute("SELECT id FROM entities WHERE invalid_at IS NULL").fetchone()[0] == "sing"
    conn.close()


def test_fresh_scan_when_store_empty(test_db):
    """Empty embedding store → every entity is new → full from-scratch normalization."""
    conn = get_connection(test_db)
    _add_entity(conn, "a", "database", sources=5)
    _add_entity(conn, "b", "databse", sources=1)   # ~auto dup of a
    _add_entity(conn, "c", "datastore", sources=1)  # ~review of a
    _add_entity(conn, "d", "frontend", sources=1)   # unrelated
    mapping = {"database": VEC["base"], "databse": VEC["auto"], "datastore": VEC["review"], "frontend": VEC["diff"]}
    with patch.object(norm, "embed_entities", _embedder(mapping)):
        res = norm.run_batch_normalization(conn)
    assert res["embedding_merges"] == 1   # b merged into a
    assert res["queued_for_review"] == 1  # a–c queued
    assert _count(conn) == 3
    # all survivors got embeddings persisted
    assert conn.execute("SELECT COUNT(*) FROM entity_embeddings").fetchone()[0] == 3
    conn.close()


def test_merged_away_new_entity_is_not_persisted(test_db):
    """A new entity that merges away must NOT get a stored embedding — else it'd
    be marked 'processed' and skipped forever."""
    conn = get_connection(test_db)
    _add_entity(conn, "old", "http client", sources=3, stored_vec=VEC["base"])
    _add_entity(conn, "new", "httpclient", sources=1)
    with patch.object(norm, "embed_entities", _embedder({"httpclient": VEC["auto"]})):
        norm.run_batch_normalization(conn)
    assert conn.execute("SELECT COUNT(*) FROM entity_embeddings WHERE entity_id='new'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM entity_embeddings WHERE entity_id='old'").fetchone()[0] == 1
    conn.close()


def test_an_invalidated_entity_is_never_normalized_against(test_db):
    """Soft-deleted entities are outside the active graph and must stay there.

    Without the `invalid_at IS NULL` filter this pass sees an entity a human
    invalidated through the corrections flow and happily merges a live entity into
    it — resurrecting the removed node as the SURVIVOR, since it has the higher
    source count. That silently undoes a human decision, which is the same class of
    bug as the judge overwriting a resolution.

    Three entities on purpose: two active, so the `len(entities) < 2` early return
    cannot make this pass for the wrong reason.
    """
    conn = get_connection(test_db)
    _add_entity(conn, "gone", "http client", sources=3, stored_vec=VEC["base"])
    conn.execute("UPDATE entities SET invalid_at = CURRENT_TIMESTAMP WHERE id = 'gone'")
    conn.commit()
    _add_entity(conn, "live", "httpclient", sources=1)          # new; ~auto-dup of 'gone'
    _add_entity(conn, "other", "frontend", stored_vec=VEC["diff"])  # keeps 2 active

    with patch.object(norm, "embed_entities", _embedder({"httpclient": VEC["auto"]})):
        res = norm.run_batch_normalization(conn)

    assert res["embedding_merges"] == 0, "merged a live entity against a soft-deleted one"
    assert res["queued_for_review"] == 0, "queued a review pair naming a removed entity"
    assert _count(conn) == 2, "active-entity count changed"
    # The invalidated row is still there, still invalid — not resurrected, not deleted.
    row = conn.execute("SELECT invalid_at FROM entities WHERE id = 'gone'").fetchone()
    assert row is not None and row[0] is not None
    conn.close()


def test_surviving_new_entity_is_persisted(test_db):
    """A new entity that survives adjudication gets its vector persisted so it's
    'old' (skipped) on the next run."""
    conn = get_connection(test_db)
    _add_entity(conn, "a", "oauth", sources=2, stored_vec=VEC["base"])
    _add_entity(conn, "b", "oauth2")  # review range → queued, not merged → survives
    with patch.object(norm, "embed_entities", _embedder({"oauth2": VEC["review"]})):
        norm.run_batch_normalization(conn)
    assert conn.execute("SELECT COUNT(*) FROM entity_embeddings WHERE entity_id='b'").fetchone()[0] == 1
    conn.close()
