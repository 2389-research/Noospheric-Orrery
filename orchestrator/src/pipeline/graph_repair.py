# ABOUTME: Pure functions for the graph self-healing correction loop (intake slice).
# Takes an injected sqlite3.Connection; no FastAPI/worker coupling. Proposing never
# mutates the graph — it only validates + inserts a pending row into graph_issues.
import sqlite3
import uuid

ALLOWED_ACTIONS = ("invalidate", "merge", "retype", "rename")


def _resolve_entity(conn: sqlite3.Connection, name_or_id: str) -> tuple[str, str]:
    """Return (entity_id, canonical_name). Accepts an exact id or a case-insensitive
    name. On multiple name matches (same-name/different-type dupes) takes the first
    by id order — deterministic; ambiguity is refined at the judge stage."""
    row = conn.execute(
        "SELECT id, canonical_name FROM entities WHERE id = ?", (name_or_id,)
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT id, canonical_name FROM entities "
            "WHERE lower(canonical_name) = lower(?) ORDER BY id LIMIT 1",
            (name_or_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"entity not found: {name_or_id!r}")
    return row[0], row[1]


def propose_correction(
    conn: sqlite3.Connection,
    *,
    action: str,
    entity: str,
    rationale: str = "",
    proposer: str = "unknown",
    target_b: str | None = None,
    proposed_type: str | None = None,
    proposed_name: str | None = None,
) -> dict:
    """Validate + resolve + insert one pending graph_issues row. Raises ValueError on
    bad action / unknown entity / missing per-action field. Returns {issue_id, status}."""
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"action must be one of {ALLOWED_ACTIONS}, got {action!r}")

    target_id, target_name = _resolve_entity(conn, entity)

    b_id = b_name = None
    if action == "merge":
        if not target_b:
            raise ValueError("merge requires target_b (the other entity)")
        b_id, b_name = _resolve_entity(conn, target_b)
        if b_id == target_id:
            raise ValueError("cannot merge an entity with itself")
    if action == "retype":
        if not (proposed_type and proposed_type.strip()):
            raise ValueError("retype requires a non-empty proposed_type")
        proposed_type = proposed_type.strip()
    if action == "rename":
        if not (proposed_name and proposed_name.strip()):
            raise ValueError("rename requires a non-empty proposed_name")
        proposed_name = proposed_name.strip()

    issue_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO graph_issues
           (id, action, target_entity_id, target_entity_name, target_b_entity_id,
            target_b_name, proposed_type, proposed_name, rationale, proposer, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
        (issue_id, action, target_id, target_name, b_id, b_name,
         proposed_type, proposed_name, rationale, proposer),
    )
    conn.commit()
    return {"issue_id": issue_id, "status": "pending"}


def get_pending_issues(conn: sqlite3.Connection) -> list[dict]:
    """All pending proposals, newest first — the queue the judge/UI consume.

    Uses a local cursor and column names from cursor.description so we never
    reassign the shared connection's row_factory (a side-effect on the caller)."""
    cursor = conn.execute(
        "SELECT * FROM graph_issues WHERE status = 'pending' ORDER BY created_at DESC"
    )
    columns = [c[0] for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _log(conn, *, action, before_value=None, after_value=None, from_entity_id=None,
         from_name=None, to_entity_id=None, to_name=None, actor="human", reason=None,
         model_verdict=None, model_confidence=None, reviewer=None):
    conn.execute(
        """INSERT INTO normalization_log
           (id, action, before_value, after_value, from_entity_id, from_name,
            to_entity_id, to_name, actor, reason, model_verdict, model_confidence, reviewer)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (str(uuid.uuid4()), action, before_value, after_value, from_entity_id, from_name,
         to_entity_id, to_name, actor, reason, model_verdict, model_confidence, reviewer),
    )


def apply_invalidation(conn, entity_id, *, reason=None, actor="human",
                       model_verdict=None, model_confidence=None, reviewer=None):
    """Soft-delete a node + its incident edges (the entire blast radius). Reversible."""
    name_row = conn.execute("SELECT canonical_name FROM entities WHERE id = ?", (entity_id,)).fetchone()
    if name_row is None:
        raise ValueError(f"entity not found: {entity_id!r}")
    conn.execute("UPDATE entities SET invalid_at = CURRENT_TIMESTAMP, invalid_reason = ?, "
                 "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND invalid_at IS NULL", (reason, entity_id))
    cur = conn.execute("UPDATE relationships SET invalid_at = CURRENT_TIMESTAMP, invalid_reason = ? "
                       "WHERE (from_entity = ? OR to_entity = ?) AND invalid_at IS NULL",
                       (reason, entity_id, entity_id))
    edges = cur.rowcount
    _log(conn, action="invalidate", before_value=name_row[0], from_entity_id=entity_id,
         from_name=name_row[0], actor=actor, reason=reason, model_verdict=model_verdict,
         model_confidence=model_confidence, reviewer=reviewer)
    conn.commit()
    return {"edges_invalidated": edges}


def rollback_invalidation(conn, entity_id):
    """Clear the soft-delete on a node + its incident edges. Exact inverse of apply_invalidation."""
    conn.execute("UPDATE entities SET invalid_at = NULL, invalid_reason = NULL WHERE id = ?", (entity_id,))
    cur = conn.execute("UPDATE relationships SET invalid_at = NULL, invalid_reason = NULL "
                       "WHERE from_entity = ? OR to_entity = ?", (entity_id, entity_id))
    conn.commit()
    return {"edges_restored": cur.rowcount}


def apply_retype(conn, entity_id, new_type, *, actor="human", reason=None,
                 model_verdict=None, model_confidence=None, reviewer=None):
    row = conn.execute("SELECT type FROM entities WHERE id = ?", (entity_id,)).fetchone()
    if row is None:
        raise ValueError(f"entity not found: {entity_id!r}")
    conn.execute("UPDATE entities SET type = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_type, entity_id))
    _log(conn, action="retype", before_value=row[0], after_value=new_type, from_entity_id=entity_id,
         actor=actor, reason=reason, model_verdict=model_verdict, model_confidence=model_confidence, reviewer=reviewer)
    conn.commit()
    return {"before": row[0], "after": new_type}


def apply_rename(conn, entity_id, new_name, *, actor="human", reason=None,
                 model_verdict=None, model_confidence=None, reviewer=None):
    row = conn.execute("SELECT canonical_name FROM entities WHERE id = ?", (entity_id,)).fetchone()
    if row is None:
        raise ValueError(f"entity not found: {entity_id!r}")
    conn.execute("UPDATE entities SET canonical_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_name, entity_id))
    _log(conn, action="rename", before_value=row[0], after_value=new_name, from_entity_id=entity_id,
         actor=actor, reason=reason, model_verdict=model_verdict, model_confidence=model_confidence, reviewer=reviewer)
    conn.commit()
    return {"before": row[0], "after": new_name}


def resolve_correction(conn, issue_id, action, *, reviewer="human"):
    """Human decision on a pending issue. action ∈ {'approve','reject'}. On approve, apply the
    issue's correction (merge is recorded but NOT applied — deferred). Reversible via the log."""
    if action not in ("approve", "reject"):
        raise ValueError("action must be 'approve' or 'reject'")
    conn.row_factory = sqlite3.Row
    issue = conn.execute("SELECT * FROM graph_issues WHERE id = ?", (issue_id,)).fetchone()
    if issue is None:
        raise ValueError(f"issue not found: {issue_id!r}")
    if issue["status"] != "pending":
        raise ValueError(f"issue already resolved: {issue['status']}")
    issue = dict(issue)

    if action == "reject":
        conn.execute("UPDATE graph_issues SET status='rejected', reviewer=?, resolved_at=CURRENT_TIMESTAMP WHERE id=?",
                     (reviewer, issue_id))
        conn.commit()
        return {"status": "rejected", "applied": False}

    kw = dict(actor="human", reason=issue.get("rationale"), model_verdict=issue.get("judge_verdict"),
              model_confidence=issue.get("judge_confidence"), reviewer=reviewer)
    applied = True
    act = issue["action"]
    if act == "invalidate":
        apply_invalidation(conn, issue["target_entity_id"], **kw)
    elif act == "retype":
        apply_retype(conn, issue["target_entity_id"], issue["proposed_type"], **kw)
    elif act == "rename":
        apply_rename(conn, issue["target_entity_id"], issue["proposed_name"], **kw)
    elif act == "merge":
        applied = False  # deferred: record the decision, do not mutate
    conn.execute("UPDATE graph_issues SET status='accepted', reviewer=?, resolved_at=CURRENT_TIMESTAMP WHERE id=?",
                 (reviewer, issue_id))
    conn.commit()
    return {"status": "accepted", "applied": applied}
