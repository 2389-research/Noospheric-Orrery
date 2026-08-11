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
from pathlib import Path

from src.db import init_db

class _Row(list):
    """Minimal stand-in for a sqlite3 row: `fetchone()[0]` is all the code reads."""
    def __init__(self, value):
        super().__init__([value])

    def fetchone(self):
        return self if self[0] is not None else None


_ORCH_DB = Path(__file__).resolve().parents[1] / "src" / "db.py"
_WORKER_DB = Path(__file__).resolve().parents[2] / "worker" / "src" / "db.py"


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


def test_a_later_edit_survives_the_next_initialization(tmp_path):
    """The backfill must not keep re-deriving from `level`.

    `level` stays populated on legacy rows forever, so a backfill gated only on
    `level IS NOT NULL` re-runs on every open and RESETS both columns from the stale
    legacy value — silently reverting whatever was written since. `emits_cooccurrence`
    exists specifically so it can be set independently of structural role, so a legacy
    row would be pinned to the level-derived value permanently, undoing an operator fix
    or a re-ingest at the next process start.
    """
    db = str(tmp_path / "legacy.db")
    _legacy_db(db)
    init_db(db)

    # Something changes its mind after the migration: a group opts INTO co-occurrence,
    # and a role is corrected. Both are legitimate writes on a legacy row.
    conn = sqlite3.connect(db)
    conn.execute("UPDATE document_collections SET emits_cooccurrence = 1 WHERE document_id = 'd2'")
    conn.execute("UPDATE document_collections SET role = 'leaf' WHERE document_id = 'd1'")
    conn.commit()
    conn.close()

    from src import db as db_mod
    db_mod._initialized.discard(db)      # a second process opens the same file
    init_db(db)

    conn = sqlite3.connect(db)
    emits = dict(conn.execute(
        "SELECT document_id, emits_cooccurrence FROM document_collections").fetchall())
    roles = dict(conn.execute(
        "SELECT document_id, role FROM document_collections").fetchall())
    conn.close()

    assert emits["d2"] == 1, "re-derived emits_cooccurrence from the stale `level`"
    assert roles["d1"] == "leaf", "re-derived role from the stale `level`"
    # Untouched rows keep their derived values — the backfill is not reverted either.
    assert roles["d3"] == "leaf" and emits["d3"] == 1


def test_two_concurrent_processes_can_open_a_legacy_database(tmp_path):
    """The orchestrator and the worker really do both open every workspace.

    With a DEFERRED transaction both processes could read the legacy schema before
    either took the write lock, and the loser would get SQLITE_BUSY_SNAPSHOT upgrading
    its stale snapshot — which `busy_timeout` cannot rescue, because waiting does not
    make an outdated snapshot current. Real subprocesses, not threads: the per-process
    `_initialized` memo and SQLite's per-connection locking are exactly what is under
    test, and threads in one process would share both.
    """
    import subprocess
    import sys
    import textwrap
    from pathlib import Path

    db = str(tmp_path / "legacy.db")
    _legacy_db(db)

    orchestrator_dir = Path(__file__).resolve().parents[1]   # .../orchestrator
    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(orchestrator_dir)!r})
        from src.db import init_db
        init_db({db!r})
        print("ok")
    """)
    # Eight, not four. At four this passed on macOS and failed on Linux CI — the race
    # window is real but narrow, and a test that only sometimes enters it is no guard at
    # all. More contenders make the collision reliable on both.
    procs = [subprocess.Popen([sys.executable, "-c", script],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for _ in range(8)]
    results = [(p.wait(timeout=90), *p.communicate()) for p in procs]

    failed = [(rc, out, err) for rc, out, err in results if rc != 0]
    assert not failed, "concurrent init_db failed:\n" + "\n".join(
        f"rc={rc}\n{err[-1500:]}" for rc, _, err in failed)

    # And the database is correctly migrated exactly once, not partially or twice.
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM collections").fetchone()[0] == 1
    roles = dict(conn.execute("SELECT document_id, role FROM document_collections").fetchall())
    conn.close()
    assert roles == {"d1": "root", "d2": "group", "d3": "leaf", "d4": "leaf"}


def test_busy_timeout_is_set_before_journal_mode(tmp_path):
    """`busy_timeout` must be set BEFORE `journal_mode=WAL`, in both db modules.

    Switching journal modes takes a brief exclusive lock, so on a database not yet in
    WAL — a fresh file, or one just imported from elsewhere — that pragma is itself a
    contended write. Set after, it runs with NO timeout in force and raises "database is
    locked" immediately. A pragma cannot be covered by a timeout that has not been set
    yet. This is what broke on Linux CI, in `get_connection`, not in the migration.

    Asserted STATICALLY, on the source order, which deserves an explanation. Two dynamic
    attempts were tried and neither is a usable guard:

      - Racing N processes and checking none fail: it reproduced on Linux CI and passed
        on macOS even with the bug reintroduced. A test that enters the window by luck
        fails to guard on whichever machine is unlucky.
      - Having a parent HOLD the write lock while a child opens: too strong. The held
        lock blocks the child at statement PREPARE time, so `busy_timeout` itself raises
        "database is locked" and the test fails identically with and without the fix —
        it stops discriminating.

    The invariant is a property of the source, so the source is what is checked. The
    multi-process test below still exercises the real thing end to end; this pins the
    one-line ordering that made it fail.
    """
    # The worker's db.py is skipped when absent rather than failing: the orchestrator
    # container image ships only `orchestrator/` + `packages/`, so in-container runs
    # cannot see it (the same constraint that makes test_schema_mirror.py native-only).
    # CI checks out the whole repo and does check both.
    checked = [p for p in (_ORCH_DB, _WORKER_DB) if p.is_file()]
    assert _ORCH_DB in checked, "the orchestrator's own db.py must always be checkable"

    for path in checked:
        source = path.read_text()
        # Scoped to get_connection's body: `PRAGMA journal_mode=WAL` also appears in
        # _enable_wal (and in its docstring), so searching the whole file finds the
        # wrong occurrence and the assertion becomes meaningless.
        body = source[source.index("def get_connection("):]
        timeout_at = body.index('PRAGMA busy_timeout')
        wal_at = body.index('_enable_wal(conn)')
        assert timeout_at < wal_at, (
            f"{path.name}: journal_mode=WAL is set before busy_timeout, so the "
            f"journal-mode switch runs with no timeout and fails immediately under "
            f"concurrent open")


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


def test_the_wal_switch_tolerates_a_concurrent_switcher():
    """Changing journal mode can return SQLITE_BUSY even with busy_timeout set.

    Setting the timeout first was necessary but NOT sufficient: CI failed on
    `PRAGMA journal_mode=WAL` with "database is locked" *after* that fix, because
    busy_timeout does not reliably cover a journal-mode change. Two processes opening the
    same not-yet-WAL file — the normal case for a freshly imported database, since both
    services open every workspace on startup — can still collide.

    Driven with a fake connection rather than a real race: the timing would not reproduce
    on macOS or in a Linux container, only on CI runners. The behaviour under test is the
    retry, not the scheduling, and `sqlite3.Connection` cannot be monkeypatched anyway.
    """
    from src.db import _enable_wal

    class BusyOnce:
        """Raises SQLITE_BUSY on the first switch, then reports success."""
        def __init__(self):
            self.switches = 0

        def execute(self, sql, *args):
            if sql.strip().lower() == "pragma journal_mode=wal":
                self.switches += 1
                if self.switches == 1:
                    raise sqlite3.OperationalError("database is locked")
                return _Row("wal")
            if sql.strip().lower() == "pragma journal_mode":
                # The first switch RAISED, so the file is still in rollback mode. A fake
                # that claimed "wal" here would let _enable_wal return early and the test
                # would pass without ever exercising the retry.
                return _Row("wal" if self.switches >= 2 else "delete")
            return _Row(None)

    conn = BusyOnce()
    _enable_wal(conn, attempts=3)          # must not raise
    assert conn.switches >= 2, "the switch was not retried after SQLITE_BUSY"


def test_the_switch_is_satisfied_when_another_process_already_did_it():
    """"Already WAL" is success, not something to keep fighting for.

    If the other process won, the work is done — retrying to exhaustion would turn a
    won race into an error.
    """
    from src.db import _enable_wal

    class AlwaysBusyButAlreadyWal:
        def __init__(self):
            self.switches = 0

        def execute(self, sql, *args):
            if sql.strip().lower() == "pragma journal_mode=wal":
                self.switches += 1
                raise sqlite3.OperationalError("database is locked")
            if sql.strip().lower() == "pragma journal_mode":
                return _Row("wal")      # someone else completed the switch
            return _Row(None)

    conn = AlwaysBusyButAlreadyWal()
    _enable_wal(conn, attempts=4)          # must not raise
    assert conn.switches == 1, "should stop as soon as the file is observed to be WAL"


def test_a_real_failure_is_not_retried_into_silence():
    """Only contention is retryable — an unwritable database must surface at once.

    Otherwise the retry loop becomes a way of hiding problems rather than surviving
    them, and a clear error arrives several seconds late wearing the wrong clothes.
    """
    import pytest

    from src.db import _enable_wal

    class ReadOnly:
        def __init__(self):
            self.switches = 0

        def execute(self, sql, *args):
            if sql.strip().lower() == "pragma journal_mode=wal":
                self.switches += 1
                raise sqlite3.OperationalError("attempt to write a readonly database")
            return _Row(None)

    conn = ReadOnly()
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        _enable_wal(conn, attempts=6)
    assert conn.switches == 1, "a non-contention error must not be retried"


def test_a_connection_is_never_returned_quietly_without_wal():
    """`PRAGMA journal_mode=WAL` REPORTS the resulting mode; it need not raise.

    So a final bare execute could leave the connection in rollback-journal mode with no
    error anywhere — silently losing the concurrent reader/writer guarantee the rest of
    this codebase assumes, which is the whole reason WAL is set. The returned value is
    the only reliable signal, so exhausting the retries on a database that never
    switches has to raise rather than return.
    """
    import pytest

    from src.db import _enable_wal

    class NeverSwitches:
        """Accepts the pragma without error and stays in `delete` — the silent case."""
        def __init__(self):
            self.switches = 0

        def execute(self, sql, *args):
            if sql.strip().lower() == "pragma journal_mode=wal":
                self.switches += 1
            return _Row("delete")

    conn = NeverSwitches()
    with pytest.raises(sqlite3.OperationalError, match="could not enable WAL"):
        _enable_wal(conn, attempts=2)
    assert conn.switches >= 2, "should have exhausted its retries before giving up"
