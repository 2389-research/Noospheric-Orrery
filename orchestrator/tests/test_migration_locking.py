# ABOUTME: The collections migration must not take a write lock when there is nothing to do.
# ABOUTME: Both services call init_db on every workspace on every poll pass.
"""Opening a database must be free when it is already migrated.

`migrate_to_collections` took `BEGIN IMMEDIATE` — an exclusive write lock — before
reading anything, so it paid for a migration on every call even though the answer was
almost always "nothing to do". Both services call `init_db` on every workspace database
they can see, and the worker does it on every 5s poll pass, so the cost was one
exclusive lock per workspace per pass forever. On a machine with ~50 workspaces that is
constant, self-inflicted contention, and it collided with genuinely long writes: an
in-flight `extract_batch` made the worker's poll loop log `database is locked` and skip
that workspace for the cycle.

The fix is a read-only precheck. These tests pin both halves of it: no lock when the
work is already done, and the migration still happens (and is still refused when
ambiguous) when it is not.
"""
from __future__ import annotations

import sqlite3

import pytest

from src.db import (
    _collections_migration_needed,
    get_connection,
    init_db,
    migrate_to_collections,
)


def _busy_writer(db_path):
    """A second connection holding the write lock, as a live peer would."""
    holder = sqlite3.connect(str(db_path))
    holder.execute("PRAGMA busy_timeout=100")
    holder.execute("BEGIN IMMEDIATE")
    holder.execute("CREATE TABLE IF NOT EXISTS _holder (x INTEGER)")
    return holder


def test_a_migrated_database_opens_while_another_process_is_writing(tmp_path):
    """The regression, stated as the symptom it caused.

    With the unconditional BEGIN IMMEDIATE this raises `database is locked` — which is
    exactly what the worker's poll loop logged while an extraction held the lock.
    """
    db_path = tmp_path / "orrery.db"
    init_db(str(db_path))

    holder = _busy_writer(db_path)
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA busy_timeout=100")   # deliberately short: no waiting it out
        try:
            migrate_to_collections(conn)          # must not need the lock at all
            assert not conn.in_transaction, "left a transaction open"
        finally:
            conn.close()
    finally:
        holder.rollback()
        holder.close()


def test_a_migrated_database_reports_no_work(tmp_path):
    db_path = tmp_path / "orrery.db"
    init_db(str(db_path))
    conn = get_connection(str(db_path))
    try:
        assert _collections_migration_needed(conn) is False
    finally:
        conn.close()


def _legacy_db(path) -> None:
    """The repo-era shape, as a pre-rename corpus actually has it."""
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE repos (id TEXT PRIMARY KEY, name TEXT, path TEXT,
                            root_path TEXT, document_count INTEGER, kind TEXT);
        CREATE TABLE document_repos (document_id TEXT, repo_id TEXT, level TEXT);
        CREATE TABLE repo_edges (source TEXT, target TEXT, type TEXT, weight REAL,
                                 PRIMARY KEY (source, target, type));
        CREATE INDEX idx_document_repos_repo ON document_repos(repo_id);
        INSERT INTO repos VALUES ('r1', 'demo', 'demo', '/data/demo', 1, 'git_repo');
    """)
    conn.commit()
    conn.close()


def test_a_legacy_database_still_reports_work_and_migrates(tmp_path):
    """The precheck must never skip a real migration — that would be silent data loss."""
    db_path = tmp_path / "orrery.db"
    _legacy_db(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        assert _collections_migration_needed(conn) is True
    finally:
        conn.close()

    init_db(str(db_path))

    conn = sqlite3.connect(str(db_path))
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "collections" in tables and "repos" not in tables
        assert conn.execute("SELECT name FROM collections").fetchone()[0] == "demo"
        # And a second pass is now free.
        assert _collections_migration_needed(conn) is False
    finally:
        conn.close()


def test_a_repo_uses_edge_still_counts_as_work(tmp_path):
    """The row-level half of the migration, which no table/column check would catch."""
    db_path = tmp_path / "orrery.db"
    init_db(str(db_path))
    conn = get_connection(str(db_path))
    try:
        conn.execute("INSERT INTO collection_edges (source, target, type, weight) "
                     "VALUES ('a', 'b', 'repo_uses', 1.0)")
        conn.commit()
        assert _collections_migration_needed(conn) is True
    finally:
        conn.close()

    # migrate_to_collections directly, not init_db: this process has already
    # initialized this path, so init_db's per-process guard would return without
    # running anything and the assertion below would pass or fail for the wrong reason.
    conn = get_connection(str(db_path))
    try:
        migrate_to_collections(conn)
        assert conn.execute(
            "SELECT type FROM collection_edges").fetchone()[0] == "uses"
        assert _collections_migration_needed(conn) is False
    finally:
        conn.close()


def test_a_half_migrated_database_is_still_refused(tmp_path):
    """The precheck must not turn a loud refusal into a quiet skip.

    Both names existing means rows live under each and no safe automatic merge exists.
    `repos` present is what trips the precheck, so the conflict still reaches the body.
    """
    db_path = tmp_path / "orrery.db"
    init_db(str(db_path))            # creates `collections`
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE repos (id TEXT PRIMARY KEY, name TEXT)")
    conn.commit()
    try:
        assert _collections_migration_needed(conn) is True
        with pytest.raises(RuntimeError, match="both names exist"):
            migrate_to_collections(conn)
    finally:
        conn.close()
