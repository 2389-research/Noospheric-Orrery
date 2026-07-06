# ABOUTME: Pure functions for the graph self-healing correction loop (intake slice).
# Takes an injected sqlite3.Connection; no FastAPI/worker coupling. Proposing never
# mutates the graph — it only validates + inserts a pending row into graph_issues.
import json
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
                       model_verdict=None, model_confidence=None, reviewer=None, commit=True):
    """Soft-delete a node + the edges *this call* invalidates (only those valid at apply
    time). The exact set of edge ids is recorded in the log's after_value so rollback can
    restore precisely those, without resurrecting edges a prior independent invalidation set."""
    name_row = conn.execute("SELECT canonical_name FROM entities WHERE id = ?", (entity_id,)).fetchone()
    if name_row is None:
        raise ValueError(f"entity not found: {entity_id!r}")
    # Capture exactly which incident edges we are about to invalidate (those still valid).
    edge_ids = [r[0] for r in conn.execute(
        "SELECT id FROM relationships WHERE (from_entity = ? OR to_entity = ?) AND invalid_at IS NULL",
        (entity_id, entity_id),
    ).fetchall()]
    conn.execute("UPDATE entities SET invalid_at = CURRENT_TIMESTAMP, invalid_reason = ?, "
                 "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND invalid_at IS NULL", (reason, entity_id))
    if edge_ids:
        ph = ",".join("?" * len(edge_ids))
        conn.execute(f"UPDATE relationships SET invalid_at = CURRENT_TIMESTAMP, invalid_reason = ? "
                     f"WHERE id IN ({ph})", [reason] + edge_ids)
    _log(conn, action="invalidate", before_value=name_row[0], after_value=json.dumps(edge_ids),
         from_entity_id=entity_id, from_name=name_row[0], actor=actor, reason=reason,
         model_verdict=model_verdict, model_confidence=model_confidence, reviewer=reviewer)
    if commit:
        conn.commit()
    return {"edges_invalidated": len(edge_ids)}


def rollback_invalidation(conn, entity_id, *, commit=True):
    """Exact inverse of apply_invalidation: restore the node + ONLY the edge ids that the
    most-recent invalidate recorded — so edges a prior independent invalidation set stay
    invalid. Audited via a `rollback_invalidate` log row."""
    row = conn.execute(
        "SELECT after_value FROM normalization_log WHERE action = 'invalidate' AND from_entity_id = ? "
        "ORDER BY rowid DESC LIMIT 1", (entity_id,),
    ).fetchone()
    edge_ids = json.loads(row[0]) if row and row[0] else []
    conn.execute("UPDATE entities SET invalid_at = NULL, invalid_reason = NULL WHERE id = ?", (entity_id,))
    if edge_ids:
        ph = ",".join("?" * len(edge_ids))
        conn.execute(f"UPDATE relationships SET invalid_at = NULL, invalid_reason = NULL "
                     f"WHERE id IN ({ph})", edge_ids)
    _log(conn, action="rollback_invalidate", after_value=json.dumps(edge_ids),
         from_entity_id=entity_id)
    if commit:
        conn.commit()
    return {"edges_restored": len(edge_ids)}


def apply_retype(conn, entity_id, new_type, *, actor="human", reason=None,
                 model_verdict=None, model_confidence=None, reviewer=None, commit=True):
    row = conn.execute("SELECT type FROM entities WHERE id = ?", (entity_id,)).fetchone()
    if row is None:
        raise ValueError(f"entity not found: {entity_id!r}")
    conn.execute("UPDATE entities SET type = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_type, entity_id))
    _log(conn, action="retype", before_value=row[0], after_value=new_type, from_entity_id=entity_id,
         actor=actor, reason=reason, model_verdict=model_verdict, model_confidence=model_confidence, reviewer=reviewer)
    if commit:
        conn.commit()
    return {"before": row[0], "after": new_type}


def apply_rename(conn, entity_id, new_name, *, actor="human", reason=None,
                 model_verdict=None, model_confidence=None, reviewer=None, commit=True):
    row = conn.execute("SELECT canonical_name FROM entities WHERE id = ?", (entity_id,)).fetchone()
    if row is None:
        raise ValueError(f"entity not found: {entity_id!r}")
    conn.execute("UPDATE entities SET canonical_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_name, entity_id))
    _log(conn, action="rename", before_value=row[0], after_value=new_name, from_entity_id=entity_id,
         actor=actor, reason=reason, model_verdict=model_verdict, model_confidence=model_confidence, reviewer=reviewer)
    if commit:
        conn.commit()
    return {"before": row[0], "after": new_name}


def _incident_edges(conn, *ids):
    ph = ",".join("?" * len(ids))
    return conn.execute(
        f"SELECT id, from_entity, to_entity, type, weight, source_chunk, invalid_at "
        f"FROM relationships WHERE from_entity IN ({ph}) OR to_entity IN ({ph})", ids + ids).fetchall()


def apply_merge(conn, loser_id, survivor_id, *, actor="human", reason=None,
                model_verdict=None, model_confidence=None, reviewer=None, commit=True):
    """Collapse loser into survivor: reattribute mentions, RECOMPUTE survivor's 1-hop co-occurrence
    edges over the combined chunk set (weights combine, no duplicates), alias the loser name, and
    SOFT-DELETE the loser. Reversible: the full before-state is snapshotted in the log."""
    ls = conn.execute("SELECT id, canonical_name FROM entities WHERE id = ?", (loser_id,)).fetchone()
    ss = conn.execute("SELECT id, canonical_name FROM entities WHERE id = ?", (survivor_id,)).fetchone()
    if ls is None or ss is None:
        raise ValueError("merge needs two existing entities")
    if loser_id == survivor_id:
        raise ValueError("cannot merge an entity with itself")

    # --- snapshot for exact undo ---
    moved_src_rowids = [r[0] for r in conn.execute(
        "SELECT rowid FROM entity_sources WHERE entity_id = ?", (loser_id,)).fetchall()]
    edge_snapshot = [list(r) for r in _incident_edges(conn, loser_id, survivor_id)]
    loser_row = {"id": ls[0], "canonical_name": ls[1]}
    snapshot = json.dumps({"loser": loser_row, "moved_src_rowids": moved_src_rowids, "edges": edge_snapshot})

    # 1. reattribute the loser's mentions to the survivor
    conn.execute("UPDATE entity_sources SET entity_id = ? WHERE entity_id = ?", (survivor_id, loser_id))

    # 2. drop old incident edges of BOTH (we recompute the survivor's from scratch)
    conn.execute("DELETE FROM relationships WHERE from_entity IN (?,?) OR to_entity IN (?,?)",
                 (loser_id, survivor_id, loser_id, survivor_id))

    # 3. recompute survivor's co-occurrence edges over its (now combined) chunk set, active neighbors only,
    #    weight = distinct shared chunks (so a shared chunk counts once). Mirrors cooccurrence.py semantics.
    rows = conn.execute(
        """SELECT es.entity_id AS neighbor, COUNT(DISTINCT es.chunk_id) AS w, MIN(es.chunk_id) AS first_chunk
             FROM entity_sources es
             JOIN entities e ON e.id = es.entity_id
            WHERE es.chunk_id IN (SELECT chunk_id FROM entity_sources WHERE entity_id = ?)
              AND es.entity_id != ?
              AND e.invalid_at IS NULL
            GROUP BY es.entity_id""",
        (survivor_id, survivor_id)).fetchall()
    for neighbor, w, first_chunk in rows:
        conn.execute("INSERT INTO relationships (id, from_entity, to_entity, type, weight, source_chunk) "
                     "VALUES (?,?,?,?,?,?)", (str(uuid.uuid4()), survivor_id, neighbor, "co_occurs", w, first_chunk))

    # 4. alias for future ingest dedup
    conn.execute("INSERT OR REPLACE INTO merge_map (from_name, to_entity_id) VALUES (?, ?)", (ls[1], survivor_id))

    # 5. soft-delete the loser (reversible)
    conn.execute("UPDATE entities SET invalid_at = CURRENT_TIMESTAMP, invalid_reason = ?, "
                 "updated_at = CURRENT_TIMESTAMP WHERE id = ?", (reason, loser_id))

    _log(conn, action="merge", before_value=ls[1], after_value=snapshot, from_entity_id=loser_id,
         from_name=ls[1], to_entity_id=survivor_id, to_name=ss[1], actor=actor, reason=reason,
         model_verdict=model_verdict, model_confidence=model_confidence, reviewer=reviewer)
    if commit:
        conn.commit()
    return {"survivor": survivor_id, "loser": loser_id, "edges_recomputed": len(rows)}


def rollback_merge(conn, loser_id, *, commit=True):
    """Exact inverse of apply_merge, from the log snapshot."""
    row = conn.execute("SELECT after_value FROM normalization_log WHERE action='merge' AND from_entity_id=? "
                       "ORDER BY rowid DESC LIMIT 1", (loser_id,)).fetchone()
    if row is None:
        raise ValueError(f"no merge log for {loser_id!r}")
    snap = json.loads(row[0])
    survivor_id = conn.execute("SELECT to_entity_id FROM merge_map WHERE to_entity_id IS NOT NULL "
                               "AND from_name = ?", (snap["loser"]["canonical_name"],)).fetchone()
    # move sources back to the loser
    if snap["moved_src_rowids"]:
        ph = ",".join("?" * len(snap["moved_src_rowids"]))
        conn.execute(f"UPDATE entity_sources SET entity_id = ? WHERE rowid IN ({ph})",
                     [loser_id] + snap["moved_src_rowids"])
    # restore the exact pre-merge incident edges: delete current, re-insert snapshot
    surv = survivor_id[0] if survivor_id else None
    conn.execute("DELETE FROM relationships WHERE from_entity IN (?,?) OR to_entity IN (?,?)",
                 (loser_id, surv, loser_id, surv))
    for e in snap["edges"]:
        conn.execute("INSERT INTO relationships (id,from_entity,to_entity,type,weight,source_chunk,invalid_at) "
                     "VALUES (?,?,?,?,?,?,?)", (e[0], e[1], e[2], e[3], e[4], e[5], e[6]))
    conn.execute("DELETE FROM merge_map WHERE from_name = ?", (snap["loser"]["canonical_name"],))
    conn.execute("UPDATE entities SET invalid_at=NULL, invalid_reason=NULL WHERE id=?", (loser_id,))
    _log(conn, action="rollback_merge", from_entity_id=loser_id, from_name=snap["loser"]["canonical_name"])
    if commit:
        conn.commit()
    return {"restored": loser_id}


def resolve_correction(conn, issue_id, action, *, reviewer="human"):
    """Human decision on a pending issue. action ∈ {'approve','reject'}. On approve, apply the
    issue's correction (merge is recorded but NOT applied — deferred). The apply + status update
    commit together (atomic): the apply_* helpers are called with commit=False and this function
    does the single commit at the end, so a crash mid-way leaves the issue pending + graph clean.
    Reversible via the log."""
    if action not in ("approve", "reject"):
        raise ValueError("action must be 'approve' or 'reject'")
    # Read the issue via a local cursor (no side-effect on the shared conn's row_factory).
    cursor = conn.execute("SELECT * FROM graph_issues WHERE id = ?", (issue_id,))
    columns = [c[0] for c in cursor.description]
    row = cursor.fetchone()
    if row is None:
        raise ValueError(f"issue not found: {issue_id!r}")
    issue = dict(zip(columns, row))
    if issue["status"] != "pending":
        raise ValueError(f"issue already resolved: {issue['status']}")

    if action == "reject":
        conn.execute("UPDATE graph_issues SET status='rejected', reviewer=?, resolved_at=CURRENT_TIMESTAMP WHERE id=?",
                     (reviewer, issue_id))
        conn.commit()
        return {"status": "rejected", "applied": False}

    kw = dict(actor="human", reason=issue.get("rationale"), model_verdict=issue.get("judge_verdict"),
              model_confidence=issue.get("judge_confidence"), reviewer=reviewer, commit=False)
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
    conn.commit()  # single atomic commit for apply + status
    return {"status": "accepted", "applied": applied}
