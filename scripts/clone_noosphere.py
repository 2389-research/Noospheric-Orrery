#!/usr/bin/env python3
# ABOUTME: Duplicate a noosphere (a workspace's SQLite DB) into an isolated, SCRUBBED clone —
# ABOUTME: the target for ccvault ingestion so entity ids resolve without touching a formal
# ABOUTME: noosphere. See docs/ccvault-ingestion.md ("Target: a COPY of the source noosphere").

import argparse
import os
import sqlite3
import sys


def _has_table(conn, name) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def clone_db(src: str, dst: str) -> sqlite3.Connection:
    """Online-backup the source (safe on a live WAL DB) into dst; return the open dst conn."""
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    dst_conn = sqlite3.connect(dst)
    try:
        with dst_conn:
            src_conn.backup(dst_conn)
    finally:
        src_conn.close()
    return dst_conn


def scrub(conn: sqlite3.Connection) -> tuple[int, int]:
    """Make the clone inert. The worker auto-discovers every workspaces/*/orrery.db and runs
    each one's due watched_sources scans + queued jobs — so a raw copy would keep re-syncing
    the source's repos/vaults INTO the clone and run inherited jobs, and stop being a
    controlled snapshot. Disable watched sources and drop non-terminal jobs."""
    ws = conn.execute("UPDATE watched_sources SET enabled = 0").rowcount if _has_table(conn, "watched_sources") else 0
    jb = conn.execute("DELETE FROM jobs WHERE status IN ('queued','running')").rowcount if _has_table(conn, "jobs") else 0
    conn.commit()
    return ws, jb


def counts(conn: sqlite3.Connection) -> dict:
    def c(q):
        try:
            return conn.execute(q).fetchone()[0]
        except Exception:
            return "?"
    return {
        "documents": c("SELECT COUNT(*) FROM documents WHERE invalid_at IS NULL"),
        "entities": c("SELECT COUNT(*) FROM entities WHERE invalid_at IS NULL"),
        "domains": c("SELECT COUNT(*) FROM domains"),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("src", help="source workspace orrery.db (read-only)")
    ap.add_argument("dst", help="destination orrery.db, e.g. <datadir>/workspaces/<clone-id>/orrery.db")
    ap.add_argument("--force", action="store_true", help="overwrite an existing destination")
    a = ap.parse_args()

    if not os.path.exists(a.src):
        sys.exit(f"source not found: {a.src}")
    if os.path.exists(a.dst) and not a.force:
        sys.exit(f"destination exists (use --force to overwrite): {a.dst}")
    if os.path.exists(a.dst) and a.force:
        os.remove(a.dst)

    conn = clone_db(a.src, a.dst)
    try:
        ws, jb = scrub(conn)
        print(f"cloned  {a.src}\n     -> {a.dst}")
        print(f"scrubbed: disabled {ws} watched_source(s), deleted {jb} non-terminal job(s)")
        print(f"counts:   {counts(conn)}")
        print("\nServe this clone in ISOLATION (its own orchestrator process/data dir) — the search "
              "index is process-global, so a shared process could answer clone queries from another "
              "workspace's index. Then POST /ingest/ccvault against it.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
