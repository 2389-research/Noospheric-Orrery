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
