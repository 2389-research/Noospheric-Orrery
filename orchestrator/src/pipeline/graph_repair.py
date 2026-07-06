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
    if action == "retype" and not (proposed_type and proposed_type.strip()):
        raise ValueError("retype requires a non-empty proposed_type")
    if action == "rename" and not (proposed_name and proposed_name.strip()):
        raise ValueError("rename requires a non-empty proposed_name")

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
    """All pending proposals, newest first — the queue the judge/UI consume."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM graph_issues WHERE status = 'pending' ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]
