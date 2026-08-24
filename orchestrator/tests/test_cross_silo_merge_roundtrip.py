# ABOUTME: Task 8 (Per-Source Silos + Provenance) — proves that a cross-silo
# ABOUTME: near-dupe merge proposal (Tasks 6/7) round-trips cleanly through the
# ABOUTME: EXISTING human-gated corrections engine (propose -> approve -> rollback).
# ABOUTME: No new production code: this is a validation test of graph_repair.py.
"""
Scenario: entity normalization is silo-scoped, so the same real-world entity
mentioned in two different silos is extracted as two distinct entity rows
(same canonical_name/type). Tasks 6/7 file a cross-silo near-dupe as a
PROPOSED merge in `graph_issues` instead of auto-merging. This test seeds
exactly that situation and drives it through the real approve + rollback
path (`resolve_correction` -> `apply_merge` / `rollback_merge`), asserting:

  1. On approval, the two entities collapse into one survivor whose silo-set
     is the UNION of both silos ({'A', 'B'}) -- the "multi-silo entity
     participates in every silo it has a source in" rule Tasks 6/7's
     scoping queries rely on.
  2. The survivor's 1-hop co-occurrence edges are recomputed over the
     combined (both-silo) chunk set.
  3. rollback_merge reverses all of it exactly: both entities distinct
     again, sources and edges restored, each entity back to its own
     single-silo membership.
"""
import sqlite3

from src.pipeline.graph_repair import propose_correction, resolve_correction, rollback_merge


def _silo_set(conn: sqlite3.Connection, entity_id: str) -> set:
    """Mirrors the Task 6/7 scoping query literally, per the task spec."""
    rows = conn.execute(
        "SELECT DISTINCT d.silo_id FROM entity_sources es "
        "JOIN documents d ON d.id = es.document_id WHERE es.entity_id = ?",
        (entity_id,),
    ).fetchall()
    return {r[0] for r in rows}


def _seed_cross_silo_dupes(store):
    """Entity X sourced only in silo 'A', entity Y (same name/type) sourced
    only in silo 'B' -- a cross-silo near-dupe pair. Each has a private
    co-occurrence neighbor (na in A, nb in B), PLUS a shared neighbor (ns)
    that co-occurs with BOTH across both silos -- so the recomputed survivor
    edges exercise weight *combining* (ns) as well as non-inflation (na/nb),
    and the round trip has real edges to restore."""
    conn = store._conn

    # Silo A: document + chunk + entity X ('stripe') + neighbor 'na'
    # co-occurring with X in the same chunk.
    store.documents.create("doc-a", "Doc A", "stripe patrick collison", "hash-a", silo_id="A")
    store.documents.create("doc-b", "Doc B", "stripe john collison", "hash-b", silo_id="B")
    conn.executescript(
        """
        INSERT INTO chunks (id, document_id, chunk_index, text) VALUES
            ('c-a1', 'doc-a', 0, 'stripe patrick collison');
        INSERT INTO chunks (id, document_id, chunk_index, text) VALUES
            ('c-b1', 'doc-b', 0, 'stripe john collison');
        """
    )
    conn.commit()

    ex = store.entities.create("ex", "stripe", "Organization")
    ey = store.entities.create("ey", "stripe", "Organization")
    na = store.entities.create("na", "patrick collison", "Person")
    nb = store.entities.create("nb", "john collison", "Person")
    ns = store.entities.create("ns", "san francisco", "Place")  # shared: in BOTH silos

    store.entity_sources.create(entity_id=ex, document_id="doc-a", chunk_id="c-a1")
    store.entity_sources.create(entity_id=na, document_id="doc-a", chunk_id="c-a1")
    store.entity_sources.create(entity_id=ey, document_id="doc-b", chunk_id="c-b1")
    store.entity_sources.create(entity_id=nb, document_id="doc-b", chunk_id="c-b1")
    # ns co-occurs with X in silo A's chunk AND with Y in silo B's chunk.
    store.entity_sources.create(entity_id=ns, document_id="doc-a", chunk_id="c-a1")
    store.entity_sources.create(entity_id=ns, document_id="doc-b", chunk_id="c-b1")

    store.relationships.upsert_cooccurrence("r-ex-na", ex, na, 1, source_chunk="c-a1")
    store.relationships.upsert_cooccurrence("r-ey-nb", ey, nb, 1, source_chunk="c-b1")
    store.relationships.upsert_cooccurrence("r-ex-ns", ex, ns, 1, source_chunk="c-a1")
    store.relationships.upsert_cooccurrence("r-ey-ns", ey, ns, 1, source_chunk="c-b1")

    return ex, ey, na, nb, ns


def test_cross_silo_merge_proposal_approves_and_rolls_back_cleanly(test_store):
    conn = test_store._conn
    ex, ey, na, nb, ns = _seed_cross_silo_dupes(test_store)

    # Sanity: pre-merge, each entity participates in exactly its own silo.
    assert _silo_set(conn, ex) == {"A"}
    assert _silo_set(conn, ey) == {"B"}

    before_edges = conn.execute(
        "SELECT id, from_entity, to_entity, weight FROM relationships ORDER BY id"
    ).fetchall()
    before_sources = conn.execute(
        "SELECT entity_id, document_id, chunk_id FROM entity_sources ORDER BY 1, 2, 3"
    ).fetchall()

    # --- File the cross-silo merge proposal, exactly as Tasks 6/7 would. ---
    proposal = propose_correction(
        conn,
        action="merge",
        entity=ex,
        target_b=ey,
        rationale="cross-silo near-dupe: same name/type across silos A and B",
        proposer="normalizer",
    )
    assert proposal["status"] == "pending"

    issue_row = conn.execute(
        "SELECT status, target_entity_id, target_b_entity_id FROM graph_issues WHERE id = ?",
        (proposal["issue_id"],),
    ).fetchone()
    assert issue_row[0] == "pending"

    # --- Approve via the REAL human-gated path. ---
    result = resolve_correction(conn, proposal["issue_id"], "approve", reviewer="human")
    assert result == {"status": "accepted", "applied": True}

    issue_status = conn.execute(
        "SELECT status FROM graph_issues WHERE id = ?", (proposal["issue_id"],)
    ).fetchone()[0]
    assert issue_status == "accepted"

    # Exactly one of {ex, ey} is now soft-deleted (the loser); the other is the
    # survivor. Source counts tie (1 each) -> resolve_correction's tie-break
    # picks target_b (ey) as survivor, but assert generically so this doesn't
    # silently start testing the tie-break instead of the round trip.
    ex_invalid = conn.execute("SELECT invalid_at FROM entities WHERE id = ?", (ex,)).fetchone()[0]
    ey_invalid = conn.execute("SELECT invalid_at FROM entities WHERE id = ?", (ey,)).fetchone()[0]
    assert (ex_invalid is None) != (ey_invalid is None), "exactly one entity must survive"
    survivor, loser = (ex, ey) if ex_invalid is None else (ey, ex)

    # --- The core assertion: the survivor is now a MULTI-SILO entity. ---
    assert _silo_set(conn, survivor) == {"A", "B"}
    # The loser's own entity_sources rows were reattributed, not left behind.
    assert conn.execute(
        "SELECT COUNT(*) FROM entity_sources WHERE entity_id = ?", (loser,)
    ).fetchone()[0] == 0

    # The survivor's 1-hop co-occurrence edges were recomputed over the
    # combined (both-silo) chunk set: it now co-occurs with BOTH neighbors.
    neighbor_ids = {
        r[0] for r in conn.execute(
            """SELECT CASE WHEN from_entity = ? THEN to_entity ELSE from_entity END
               FROM relationships
               WHERE (from_entity = ? OR to_entity = ?) AND type = 'co_occurs'
                 AND invalid_at IS NULL""",
            (survivor, survivor, survivor),
        ).fetchall()
    }
    assert neighbor_ids == {na, nb, ns}

    # Weights COMBINE, they don't double-count (the #30 / graph-corrections
    # invariant that apply_merge's recompute exists to preserve). Recompute
    # weight = COUNT(DISTINCT shared chunk); the survivor now sources {c-a1, c-b1}:
    #   - na shares only c-a1 -> 1 (single-silo neighbor NOT inflated by the merge)
    #   - nb shares only c-b1 -> 1
    #   - ns shares BOTH      -> 2 (combined across silos; a shared chunk counted once)
    weights = {
        r[0]: r[1] for r in conn.execute(
            """SELECT CASE WHEN from_entity = ? THEN to_entity ELSE from_entity END, weight
               FROM relationships
               WHERE (from_entity = ? OR to_entity = ?) AND type = 'co_occurs'
                 AND invalid_at IS NULL""",
            (survivor, survivor, survivor),
        ).fetchall()
    }
    assert weights == {na: 1, nb: 1, ns: 2}

    # No active edge still references the loser directly.
    assert conn.execute(
        "SELECT COUNT(*) FROM relationships WHERE (from_entity = ? OR to_entity = ?) "
        "AND invalid_at IS NULL",
        (loser, loser),
    ).fetchone()[0] == 0

    # --- Roll back via the real inverse. ---
    rollback = rollback_merge(conn, loser_id=loser)
    assert rollback["restored"] == loser
    assert rollback["sourceless"] is False

    # Both entities distinct again: loser's invalid_at cleared.
    assert conn.execute(
        "SELECT invalid_at FROM entities WHERE id = ?", (loser,)
    ).fetchone()[0] is None
    assert conn.execute(
        "SELECT invalid_at FROM entities WHERE id = ?", (survivor,)
    ).fetchone()[0] is None

    # Sources and edges restored EXACTLY to the pre-merge state.
    after_sources = conn.execute(
        "SELECT entity_id, document_id, chunk_id FROM entity_sources ORDER BY 1, 2, 3"
    ).fetchall()
    after_edges = conn.execute(
        "SELECT id, from_entity, to_entity, weight FROM relationships ORDER BY id"
    ).fetchall()
    assert after_sources == before_sources
    assert after_edges == before_edges

    # Each entity is back to its own single silo -- the multi-silo membership
    # does not leak past the undo.
    assert _silo_set(conn, ex) == {"A"}
    assert _silo_set(conn, ey) == {"B"}

    # merge_map alias created by the merge is cleared by the rollback (no
    # prior alias existed for this name in this test's fixture).
    loser_name = conn.execute(
        "SELECT canonical_name FROM entities WHERE id = ?", (loser,)
    ).fetchone()[0]
    assert conn.execute(
        "SELECT COUNT(*) FROM merge_map WHERE from_name = ?", (loser_name,)
    ).fetchone()[0] == 0
