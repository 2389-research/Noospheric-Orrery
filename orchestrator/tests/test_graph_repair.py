import sqlite3
import pytest
from src.db import init_db
from src.pipeline.graph_repair import propose_correction, get_pending_issues, ALLOWED_ACTIONS


def _seed(test_db):
    conn = sqlite3.connect(test_db)
    conn.row_factory = sqlite3.Row
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'panopticon', 'Product')")
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e2', 'websim', 'Product')")
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e3', 'web sim', 'Product')")
    conn.commit()
    return conn


def test_propose_invalidate_inserts_pending_row(test_db):
    conn = _seed(test_db)
    res = propose_correction(conn, action="invalidate", entity="panopticon",
                             rationale="metaphor, not a real product", proposer="agent-x")
    assert res["status"] == "pending"
    row = conn.execute("SELECT * FROM graph_issues WHERE id = ?", (res["issue_id"],)).fetchone()
    assert row["action"] == "invalidate"
    assert row["target_entity_id"] == "e1"
    assert row["target_entity_name"] == "panopticon"
    assert row["proposer"] == "agent-x"


def test_propose_merge_requires_and_resolves_second_entity(test_db):
    conn = _seed(test_db)
    res = propose_correction(conn, action="merge", entity="web sim", target_b="websim",
                             rationale="spacing variant")
    row = conn.execute("SELECT * FROM graph_issues WHERE id = ?", (res["issue_id"],)).fetchone()
    assert row["target_entity_id"] == "e3"
    assert row["target_b_entity_id"] == "e2"


def test_propose_merge_self_raises(test_db):
    conn = _seed(test_db)
    # entity and target_b resolve to the same id (case-insensitive) -> reject.
    with pytest.raises(ValueError, match="itself"):
        propose_correction(conn, action="merge", entity="websim", target_b="WebSim")


def test_propose_retype_records_proposed_type(test_db):
    conn = _seed(test_db)
    res = propose_correction(conn, action="retype", entity="panopticon", proposed_type="Concept")
    row = conn.execute("SELECT proposed_type FROM graph_issues WHERE id = ?", (res["issue_id"],)).fetchone()
    assert row["proposed_type"] == "Concept"


def test_propose_rename_records_proposed_name(test_db):
    conn = _seed(test_db)
    res = propose_correction(conn, action="rename", entity="websim", proposed_name="WebSim")
    row = conn.execute("SELECT proposed_name FROM graph_issues WHERE id = ?", (res["issue_id"],)).fetchone()
    assert row["proposed_name"] == "WebSim"


def test_propose_unknown_entity_raises(test_db):
    conn = _seed(test_db)
    with pytest.raises(ValueError, match="not found"):
        propose_correction(conn, action="invalidate", entity="does-not-exist")


def test_propose_bad_action_raises(test_db):
    conn = _seed(test_db)
    with pytest.raises(ValueError, match="action"):
        propose_correction(conn, action="frobnicate", entity="panopticon")


def test_propose_merge_without_target_b_raises(test_db):
    conn = _seed(test_db)
    with pytest.raises(ValueError, match="target_b"):
        propose_correction(conn, action="merge", entity="web sim")


def test_propose_retype_without_type_raises(test_db):
    conn = _seed(test_db)
    with pytest.raises(ValueError, match="proposed_type"):
        propose_correction(conn, action="retype", entity="panopticon")


def test_propose_rename_without_name_raises(test_db):
    conn = _seed(test_db)
    with pytest.raises(ValueError, match="proposed_name"):
        propose_correction(conn, action="rename", entity="websim")


def test_get_pending_issues_returns_only_pending(test_db):
    conn = _seed(test_db)
    r = propose_correction(conn, action="invalidate", entity="panopticon")
    conn.execute("UPDATE graph_issues SET status='rejected' WHERE id=?", (r["issue_id"],))
    propose_correction(conn, action="invalidate", entity="websim")
    conn.commit()
    pending = get_pending_issues(conn)
    assert len(pending) == 1
    assert pending[0]["target_entity_name"] == "websim"


def _seed_entity_with_edge(conn):
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1','panopticon','Product')")
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e2','ebay','Organization')")
    conn.execute("INSERT INTO relationships (id, from_entity, to_entity, type, weight) VALUES ('r1','e1','e2','co_occurs',3)")
    conn.commit()


def test_apply_invalidation_round_trips(test_db):
    import sqlite3
    from src.pipeline.graph_repair import apply_invalidation, rollback_invalidation
    conn = sqlite3.connect(test_db); _seed_entity_with_edge(conn)
    r = apply_invalidation(conn, "e1", reason="metaphor", actor="human")
    assert r["edges_invalidated"] == 1
    assert conn.execute("SELECT invalid_at FROM entities WHERE id='e1'").fetchone()[0] is not None
    assert conn.execute("SELECT invalid_at FROM relationships WHERE id='r1'").fetchone()[0] is not None
    assert conn.execute("SELECT invalid_at FROM entities WHERE id='e2'").fetchone()[0] is None  # neighbor untouched
    back = rollback_invalidation(conn, "e1")
    assert back["edges_restored"] == 1
    assert conn.execute("SELECT invalid_at FROM entities WHERE id='e1'").fetchone()[0] is None
    assert conn.execute("SELECT invalid_at FROM relationships WHERE id='r1'").fetchone()[0] is None


def test_apply_retype_and_rename_log(test_db):
    import sqlite3
    from src.pipeline.graph_repair import apply_retype, apply_rename
    conn = sqlite3.connect(test_db); _seed_entity_with_edge(conn)
    apply_retype(conn, "e1", "Concept", actor="human", reason="x")
    assert conn.execute("SELECT type FROM entities WHERE id='e1'").fetchone()[0] == "Concept"
    apply_rename(conn, "e2", "eBay", actor="human", reason="x")
    assert conn.execute("SELECT canonical_name FROM entities WHERE id='e2'").fetchone()[0] == "eBay"
    logs = conn.execute("SELECT action, before_value, after_value FROM normalization_log ORDER BY action").fetchall()
    assert ("rename","ebay","eBay") in [(a,b,c) for a,b,c in logs]
    assert ("retype","Product","Concept") in [(a,b,c) for a,b,c in logs]


def test_resolve_reject_sets_status_only(test_db):
    import sqlite3
    from src.pipeline.graph_repair import propose_correction, resolve_correction
    conn = sqlite3.connect(test_db); _seed_entity_with_edge(conn)
    iid = propose_correction(conn, action="invalidate", entity="panopticon")["issue_id"]
    resolve_correction(conn, iid, "reject", reviewer="human")
    row = conn.execute("SELECT status, reviewer FROM graph_issues WHERE id=?", (iid,)).fetchone()
    assert row[0] == "rejected" and row[1] == "human"
    assert conn.execute("SELECT invalid_at FROM entities WHERE id='e1'").fetchone()[0] is None  # no mutation


def test_resolve_approve_invalidate_mutates(test_db):
    import sqlite3
    from src.pipeline.graph_repair import propose_correction, resolve_correction
    conn = sqlite3.connect(test_db); _seed_entity_with_edge(conn)
    iid = propose_correction(conn, action="invalidate", entity="panopticon", rationale="metaphor")["issue_id"]
    resolve_correction(conn, iid, "approve", reviewer="human")
    assert conn.execute("SELECT status FROM graph_issues WHERE id=?", (iid,)).fetchone()[0] == "accepted"
    assert conn.execute("SELECT invalid_at FROM entities WHERE id='e1'").fetchone()[0] is not None
    assert conn.execute("SELECT COUNT(*) FROM normalization_log WHERE action='invalidate'").fetchone()[0] == 1


def test_resolve_approve_merge_records_without_mutation(test_db):
    import sqlite3
    from src.pipeline.graph_repair import propose_correction, resolve_correction
    conn = sqlite3.connect(test_db); _seed_entity_with_edge(conn)
    iid = propose_correction(conn, action="merge", entity="panopticon", target_b="ebay")["issue_id"]
    res = resolve_correction(conn, iid, "approve", reviewer="human")
    assert conn.execute("SELECT status FROM graph_issues WHERE id=?", (iid,)).fetchone()[0] == "accepted"
    # merge apply deferred → no entity removed, no invalid_at set
    assert conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 2
    assert res.get("applied") is False


def test_apply_schema_columns_exist(test_db):
    import sqlite3
    conn = sqlite3.connect(test_db)
    ecols = {r[1] for r in conn.execute("PRAGMA table_info(entities)").fetchall()}
    rcols = {r[1] for r in conn.execute("PRAGMA table_info(relationships)").fetchall()}
    lcols = {r[1] for r in conn.execute("PRAGMA table_info(normalization_log)").fetchall()}
    conn.close()
    assert {"invalid_at", "invalid_reason", "updated_at"} <= ecols
    assert {"invalid_at", "invalid_reason"} <= rcols
    assert {"action", "before_value", "after_value", "actor", "reason",
            "model_verdict", "model_confidence", "reviewer"} <= lcols


def test_graph_issues_table_exists(test_db):
    import sqlite3
    conn = sqlite3.connect(test_db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(graph_issues)").fetchall()}
    conn.close()
    assert {
        "id", "action", "target_entity_id", "target_entity_name",
        "target_b_entity_id", "target_b_name", "proposed_type", "proposed_name",
        "rationale", "proposer", "status", "judge_verdict", "judge_confidence",
        "judge_rationale", "reviewer", "created_at", "resolved_at",
    } <= cols
