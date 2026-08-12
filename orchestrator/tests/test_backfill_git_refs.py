# ABOUTME: Guards on the git-provenance backfill — the paths that can destroy or misattribute it.
# ABOUTME: Lives here because CI runs only orchestrator/tests; scripts/ has no suite.
"""The backfill writes provenance nobody verified by hand.

Its whole value is that a `git_ref` can be trusted, so the failures worth testing are
the ones that leave a ref which resolves perfectly and points at the wrong thing —
or that overwrite real, captured provenance with an approximation.

`resolve()` is not exercised here: it shells out to `gh` against live GitHub. What is
tested is every path that writes to the database.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

from src.db import get_connection, init_db

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load():
    spec = importlib.util.spec_from_file_location(
        "backfill_git_refs", SCRIPTS / "backfill_git_refs.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["backfill_git_refs"] = mod
    spec.loader.exec_module(mod)
    return mod


backfill = _load()


def _db(tmp_path, rows):
    """rows: (path, name, kind, remote_url, commit_sha)"""
    db_path = tmp_path / "orrery.db"
    init_db(str(db_path))
    conn = get_connection(str(db_path))
    for i, (path, name, kind, remote, sha) in enumerate(rows):
        conn.execute(
            "INSERT INTO collections (id, name, path, root_path, kind, remote_url, commit_sha) "
            "VALUES (?,?,?,?,?,?,?)",
            (f"c{i}", name, path, f"/data/repos/{name}", kind, remote, sha))
    conn.commit()
    conn.close()
    return db_path


def _read(db_path, path):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    row = conn.execute(
        "SELECT remote_url, commit_sha FROM collections WHERE path = ?", (path,)).fetchone()
    conn.close()
    return row


def test_a_row_missing_both_fields_is_filled(tmp_path):
    db_path = _db(tmp_path, [("tracker", "tracker", "git_repo", None, None)])
    n = backfill.apply(str(db_path), {
        "tracker": {"name": "tracker", "remote": "github.com/org/tracker", "sha": "a" * 40}})
    assert n == 1
    assert _read(db_path, "tracker") == ("github.com/org/tracker", "a" * 40)


def test_a_captured_commit_sha_is_never_replaced(tmp_path):
    """The destructive case.

    Selecting rows on "either field is null" and then writing BOTH columns replaces a
    real ingest-time SHA — the only accurate provenance the row had — with the current
    default-branch HEAD. Nothing announces it, and the resulting ref looks perfectly
    valid while pointing at code the summaries were not written from.
    """
    db_path = _db(tmp_path, [("tracker", "tracker", "git_repo", None, "real-ingest-sha")])
    n = backfill.apply(str(db_path), {
        "tracker": {"name": "tracker", "remote": "github.com/org/tracker", "sha": "b" * 40}})
    assert n == 0, "overwrote a row that already held real provenance"
    assert _read(db_path, "tracker") == (None, "real-ingest-sha")


def test_a_fully_populated_row_is_left_alone(tmp_path):
    db_path = _db(tmp_path, [("tracker", "tracker", "git_repo", "github.com/org/tracker", "c" * 40)])
    assert backfill.apply(str(db_path), {
        "tracker": {"name": "tracker", "remote": "github.com/other/x", "sha": "d" * 40}}) == 0
    assert _read(db_path, "tracker") == ("github.com/org/tracker", "c" * 40)


def test_a_stale_map_cannot_attribute_another_repo(tmp_path):
    """Split resolve/apply means the map can be old.

    A collection deleted and re-created at the same `path` would, on a path-only
    predicate, receive provenance belonging to a different repository — a ref that
    resolves and is wrong, which is precisely what this feature exists to prevent.
    """
    db_path = _db(tmp_path, [("shared-path", "different-repo", "git_repo", None, None)])
    n = backfill.apply(str(db_path), {
        "shared-path": {"name": "the-old-repo", "remote": "github.com/org/the-old-repo",
                        "sha": "e" * 40}})
    assert n == 0, "applied a stale mapping to a different repository"
    assert _read(db_path, "shared-path") == (None, None)


def test_a_tracker_run_is_never_given_a_github_ref(tmp_path):
    """A run is named for the run (`run1`), not a repo. Resolving that against the
    org would at best 404 and at worst match an unrelated repository."""
    db_path = _db(tmp_path, [("run1", "run1", "tracker_run", None, None)])
    assert backfill.apply(str(db_path), {
        "run1": {"name": "run1", "remote": "github.com/org/run1", "sha": "f" * 40}}) == 0
    assert _read(db_path, "run1") == (None, None)


@pytest.mark.parametrize("entry", [
    {"remote": "github.com/org/x", "sha": "a" * 40},          # no name
    {"name": "x", "sha": "a" * 40},                            # no remote
    {"name": "x", "remote": "github.com/org/x"},               # no sha
    {},
])
def test_an_incomplete_mapping_entry_writes_nothing(tmp_path, entry):
    db_path = _db(tmp_path, [("x", "x", "git_repo", None, None)])
    assert backfill.apply(str(db_path), {"x": entry}) == 0
    assert _read(db_path, "x") == (None, None)
