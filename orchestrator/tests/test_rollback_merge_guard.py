"""Reconciliation guard: rollback_merge must not resurrect a sourceless entity.

Document deletion (hard-delete of entity_sources) can remove the very rows a
later rollback_merge would re-target back to the loser. If that leaves the
loser with zero sources, un-invalidating it produces an orphan phantom node.
The invariant: only bring an entity back to the active graph if it still has
at least one source.
"""

from src.db import get_connection, init_db
from src.pipeline.graph_repair import apply_merge, rollback_merge


def _seed(db_path):
    conn = get_connection(db_path)
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('loser', 'gpt4', 'Product')")
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('surv', 'gpt-4', 'Product')")
    # loser sourced only by document d1; survivor by d2
    conn.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES ('loser', 'd1')")
    conn.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES ('surv', 'd2')")
    conn.commit()
    return conn


def test_rollback_restores_loser_when_sources_intact(test_db):
    conn = _seed(test_db)
    apply_merge(conn, "loser", "surv")
    rollback_merge(conn, "loser")
    row = conn.execute("SELECT invalid_at FROM entities WHERE id = 'loser'").fetchone()
    # sources intact → loser comes back to the active graph
    assert row["invalid_at"] is None


def test_rollback_keeps_loser_invalid_when_its_sources_were_deleted(test_db):
    conn = _seed(test_db)
    apply_merge(conn, "loser", "surv")
    # Simulate deleting document d1 (its source row was re-targeted to 'surv' by the merge).
    conn.execute("DELETE FROM entity_sources WHERE document_id = 'd1'")
    conn.commit()

    rollback_merge(conn, "loser")

    row = conn.execute("SELECT invalid_at FROM entities WHERE id = 'loser'").fetchone()
    src = conn.execute("SELECT COUNT(*) c FROM entity_sources WHERE entity_id = 'loser'").fetchone()["c"]
    # loser has no sources → must NOT be resurrected as an orphan
    assert src == 0
    assert row["invalid_at"] is not None
