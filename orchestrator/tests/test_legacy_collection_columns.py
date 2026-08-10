"""A RENAMED legacy table keeps its old columns, and the reads need the new ones.

`migrate_to_collections` fixes the table and column NAMES. It cannot fix the column
SET: `CREATE TABLE IF NOT EXISTS collections` adds nothing to a table that already
exists, so a pre-rename corpus arrives correctly named and wrongly shaped. Every read
that selects `role` or filters `emits_cooccurrence = 1` then fails on it — and those
are the reads that build the whole collection layer of the graph.

The `level` guard is specific to THIS schema and has no counterpart upstream: the
schema here never declares `level`, so the backfill has to check for the column's
presence. A version that assumes it (correct where `level` is still declared) raises
"no such column: level" on every fresh database — which is to say, on every test and
every new install.
"""

import sqlite3

from src.db import init_db


def _legacy_db(path, *, with_level=True):
    """A pre-rename corpus: repo-era table names, repo-era column set."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE repos (
            id TEXT PRIMARY KEY, name TEXT, path TEXT UNIQUE, root_path TEXT,
            parent_path TEXT, document_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE repo_edges (
            from_repo TEXT, to_repo TEXT, type TEXT, weight REAL DEFAULT 1.0,
            PRIMARY KEY (from_repo, to_repo, type)
        );
    """)
    level_col = "level TEXT," if with_level else ""
    conn.executescript(f"""
        CREATE TABLE document_repos (
            document_id TEXT, repo_id TEXT, {level_col} parent_path TEXT,
            PRIMARY KEY (document_id, repo_id)
        );
    """)
    conn.execute("INSERT INTO repos (id, name, path, root_path) VALUES ('r1','demo','demo','/x')")
    if with_level:
        for doc, lvl in [("d1", "repo"), ("d2", "module"), ("d3", "file"), ("d4", "file")]:
            conn.execute("INSERT INTO document_repos (document_id, repo_id, level, parent_path) "
                         "VALUES (?, 'r1', ?, 'demo')", (doc, lvl))
    conn.commit()
    conn.close()


def test_a_renamed_legacy_table_gains_the_columns_the_reads_need(tmp_path):
    db = str(tmp_path / "legacy.db")
    _legacy_db(db)

    init_db(db)

    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(document_collections)")}
    assert {"role", "emits_cooccurrence"} <= cols, (
        "the rename moved the table but not the column set, so the collection reads "
        "would fail on every migrated corpus")
    assert "kind" in {r[1] for r in conn.execute("PRAGMA table_info(collections)")}
    conn.close()


def test_role_and_emits_are_derived_from_the_overloaded_level(tmp_path):
    """`level` conflated structural role with a co-occurrence switch; both are recovered.

    Asserted as a mapping rather than a count so a silent off-by-one in the CASE
    expression cannot pass: repo->root, module->group, file->leaf, and only a file
    emits co-occurrence (which is exactly what `level == 'file'` used to gate).
    """
    db = str(tmp_path / "legacy.db")
    _legacy_db(db)

    init_db(db)

    conn = sqlite3.connect(db)
    rows = dict(conn.execute(
        "SELECT document_id, role FROM document_collections").fetchall())
    emits = dict(conn.execute(
        "SELECT document_id, emits_cooccurrence FROM document_collections").fetchall())
    conn.close()

    assert rows == {"d1": "root", "d2": "group", "d3": "leaf", "d4": "leaf"}
    assert emits == {"d1": 0, "d2": 0, "d3": 1, "d4": 1}


def test_a_fresh_database_has_no_level_column_and_must_not_crash(tmp_path):
    """The guard this schema needs and the upstream one does not.

    `level` is not in this SCHEMA, so on a fresh database the backfill's UPDATE would
    raise "no such column: level" — during init_db, i.e. before anything can be read
    or written at all.
    """
    db = str(tmp_path / "fresh.db")

    init_db(db)          # must not raise

    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(document_collections)")}
    assert "level" not in cols, "this schema should never create the deprecated column"
    assert {"role", "emits_cooccurrence"} <= cols
    conn.close()


def test_a_legacy_table_without_level_still_gets_the_new_columns(tmp_path):
    """Not every pre-rename corpus has `level` — the ALTERs must not depend on it.

    Only the backfill UPDATE is conditional on the column; adding `role` and
    `emits_cooccurrence` is unconditional, or such a corpus stays unreadable.
    """
    db = str(tmp_path / "legacy_nolevel.db")
    _legacy_db(db, with_level=False)

    init_db(db)

    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(document_collections)")}
    conn.close()
    assert {"role", "emits_cooccurrence"} <= cols


def test_the_migration_is_idempotent_across_processes(tmp_path):
    """init_db memoizes per process, so a second *process* re-runs the whole thing.

    That is the real-world case — the orchestrator and the worker both open every
    workspace — and re-running must not double-apply or raise.
    """
    db = str(tmp_path / "legacy.db")
    _legacy_db(db)

    init_db(db)
    # Clear the per-process memo to simulate a second process opening the same file.
    from src import db as db_mod
    db_mod._initialized.discard(db)
    init_db(db)          # must not raise

    conn = sqlite3.connect(db)
    rows = dict(conn.execute("SELECT document_id, role FROM document_collections").fetchall())
    n_collections = conn.execute("SELECT COUNT(*) FROM collections").fetchone()[0]
    conn.close()
    assert rows == {"d1": "root", "d2": "group", "d3": "leaf", "d4": "leaf"}
    assert n_collections == 1, "the collection row was duplicated by a second migration"
