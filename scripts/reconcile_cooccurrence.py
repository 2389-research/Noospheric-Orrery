#!/usr/bin/env python3
# ABOUTME: Global recompute of co_occurs edges as a pure projection of entity_sources.
# ABOUTME: REQUIRED once per workspace when upgrading an existing (pre-projection) graph.
"""
Rewrite every valid `co_occurs` row in a workspace as the projection of `entity_sources`
(spec 2026-08-14 incremental-source-sync §9). Two entities co-occur when they share a
chunk; weight = number of shared chunks; a document whose `emits_cooccurrence = 0`
(a repo/tracker rollup or module summary) contributes nothing; human-invalidated edges
(`invalid_at NOT NULL`) are preserved and never revived.

WHEN TO RUN THIS. On a FRESH workspace it is unnecessary (every edge is already a
projection). When UPGRADING AN EXISTING graph it is REQUIRED, once per workspace, before
the graph is trusted: `recompute_cooccurrence` only reconciles the neighbourhoods a later
ingest/update/delete happens to touch, so untouched neighbourhoods keep their legacy
rows. The old repo-ingest (aggregated `source_chunk` NULL) rows already match the new
projection weight, but the old upload-path per-chunk rows (`source_chunk` set) can
DOUBLE-COUNT against a projected row until that neighbourhood is recomputed. This pass
collapses every legacy neighbourhood at once.

Bounded, pure SQL, no model calls. Idempotent — a second run over an already-projected
DB is a no-op (the co_occurs count is stable).

Usage:
    # one workspace / DB
    python scripts/reconcile_cooccurrence.py --db ./data/orrery.db
    python scripts/reconcile_cooccurrence.py --db ./data/workspaces/<ws>/orrery.db --dry-run
    # every workspace under a data dir (the deploy step)
    python scripts/reconcile_cooccurrence.py --all-workspaces --data-dir ./data
"""
import argparse
import os
import sys
from pathlib import Path

# Make the orchestrator package importable (`from src.db import ...`), regardless of cwd.
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "orchestrator"))

from src.db import get_connection, recompute_cooccurrence  # noqa: E402


def _find_workspace_dbs(data_dir: str) -> list[str]:
    """Every workspace DB under `data_dir`: {data_dir}/workspaces/*/orrery.db plus the
    legacy flat {data_dir}/orrery.db. Mirrors the worker's discovery."""
    dbs = []
    ws_dir = os.path.join(data_dir, "workspaces")
    if os.path.isdir(ws_dir):
        for name in sorted(os.listdir(ws_dir)):
            db = os.path.join(ws_dir, name, "orrery.db")
            if os.path.isfile(db):
                dbs.append(db)
    flat = os.path.join(data_dir, "orrery.db")
    if os.path.isfile(flat) and flat not in dbs:
        dbs.append(flat)
    return dbs


def _valid_count(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) c FROM relationships WHERE type='co_occurs' AND invalid_at IS NULL"
    ).fetchone()["c"]


def reconcile(db_path: str, *, dry_run: bool = False) -> dict:
    conn = get_connection(db_path)
    try:
        before = _valid_count(conn)
        active_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM entities WHERE invalid_at IS NULL")]
        if dry_run:
            return {"active_entities": len(active_ids), "valid_co_occurs_before": before,
                    "valid_co_occurs_after": before, "applied": False}
        recompute_cooccurrence(conn, active_ids)
        conn.commit()
        after = _valid_count(conn)
        return {"active_entities": len(active_ids), "valid_co_occurs_before": before,
                "valid_co_occurs_after": after, "applied": True}
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Global recompute of co_occurs as a projection of entity_sources. "
                    "REQUIRED once per workspace when upgrading an existing graph.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--db", help="path to a single orrery SQLite DB")
    src.add_argument("--all-workspaces", action="store_true",
                     help="reconcile every workspace DB under --data-dir (the deploy step)")
    ap.add_argument("--data-dir", default="./data",
                    help="base data dir for --all-workspaces (default ./data)")
    ap.add_argument("--dry-run", action="store_true", help="report counts without writing")
    args = ap.parse_args()

    if args.all_workspaces:
        dbs = _find_workspace_dbs(args.data_dir)
        if not dbs:
            print(f"no workspace DBs found under {args.data_dir!r}", file=sys.stderr)
            sys.exit(1)
        print(f"reconciling {len(dbs)} workspace DB(s) under {args.data_dir} ...")
    else:
        dbs = [args.db]

    verb = "would reconcile" if args.dry_run else "reconciled"
    for db in dbs:
        r = reconcile(db, dry_run=args.dry_run)
        print(f"{db}: {verb} {r['active_entities']} active entities: "
              f"{r['valid_co_occurs_before']} -> {r['valid_co_occurs_after']} valid co_occurs rows")


if __name__ == "__main__":
    main()
