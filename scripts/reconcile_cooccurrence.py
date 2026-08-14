#!/usr/bin/env python3
# ABOUTME: One-time global recompute of co_occurs edges as a pure projection of entity_sources.
# ABOUTME: OPTIONAL — the pipeline reconciles lazily per neighbourhood; this is an immediate pass.
"""
Rewrite every valid `co_occurs` row in a workspace as the projection of `entity_sources`
(spec 2026-08-14 incremental-source-sync 9). Two entities co-occur when they share a
chunk; weight = number of shared chunks; a document whose `emits_cooccurrence = 0`
(a repo/tracker rollup or module summary) contributes nothing; human-invalidated edges
(`invalid_at NOT NULL`) are preserved and never revived.

WHY THIS IS OPTIONAL. `recompute_cooccurrence` deletes *all* valid co_occurs rows
touching an affected entity before rebuilding, so the first time any entity is touched
by an ingest / update / delete its legacy rows (the old aggregated `source_chunk` NULL
rows from extract_batch and the per-pair `source_chunk` rows from uploads) are cleaned
and rebuilt correctly. Reconciliation is therefore lazy and per-neighbourhood; this
script is just an immediate global collapse of legacy rows after deploy, not a
correctness gate.

Bounded, pure SQL, no model calls. Idempotent — a second run over an already-projected
DB is a no-op (the co_occurs count is stable).

Usage:
    python scripts/reconcile_cooccurrence.py --db ~/orrery-data/orrery.db
    python scripts/reconcile_cooccurrence.py --db ./data/workspaces/<ws>/orrery.db --dry-run
"""
import argparse
import sys
from pathlib import Path

# Make the orchestrator package importable (`from src.db import ...`), regardless of cwd.
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "orchestrator"))

from src.db import get_connection, recompute_cooccurrence  # noqa: E402


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
        description="Global recompute of co_occurs as a projection of entity_sources "
                    "(optional; the pipeline reconciles lazily — see the module docstring).")
    ap.add_argument("--db", required=True, help="path to the orrery SQLite DB")
    ap.add_argument("--dry-run", action="store_true",
                    help="report counts without writing")
    args = ap.parse_args()

    result = reconcile(args.db, dry_run=args.dry_run)
    verb = "would reconcile" if args.dry_run else "reconciled"
    print(f"{verb} {result['active_entities']} active entities: "
          f"{result['valid_co_occurs_before']} -> {result['valid_co_occurs_after']} "
          f"valid co_occurs rows")


if __name__ == "__main__":
    main()
