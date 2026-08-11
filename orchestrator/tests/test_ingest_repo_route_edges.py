"""Failure paths of POST /ingest/repo that leave the workspace unusable if wrong.

The happy path is covered in test_ingest_repo.py. What is here is the set of ways this
route can fail *after* committing something, because `collections.path` is UNIQUE and
this route answers 409 on a repeat — so a half-finished create does not just lose one
request, it blocks every future attempt at the same repo.
"""

import pytest


def test_a_duplicate_name_is_a_conflict_not_a_server_error(test_client, test_store, tmp_path):
    body = {"path": str(tmp_path), "name": "dup-repo"}
    first = test_client.post("/ingest/repo", json=body)
    assert first.status_code == 202, first.text

    second = test_client.post("/ingest/repo", json=body)
    assert second.status_code == 409
    assert "dup-repo" in second.json()["detail"]


def test_the_conflict_survives_the_lookup_being_raced(test_client, test_store, tmp_path, monkeypatch):
    """`get_by_path` is a check, not a lock — the UNIQUE constraint is what decides.

    Two requests can both see no collection and both proceed. Simulated by making the
    pre-check blind, which is exactly what the loser of a real race experiences: the
    insert raises IntegrityError. It must still read as 409, so a race and a repeat look
    the same to the caller instead of one of them being a 500.
    """
    assert test_client.post("/ingest/repo", json={"path": str(tmp_path), "name": "raced"}).status_code == 202

    monkeypatch.setattr(
        type(test_store.collections), "get_by_path", lambda self, path: None)

    resp = test_client.post("/ingest/repo", json={"path": str(tmp_path), "name": "raced"})
    assert resp.status_code == 409, (
        f"expected the UNIQUE violation to surface as a conflict, got {resp.status_code}: "
        f"{resp.text[:300]}")


def test_a_failed_enqueue_leaves_no_orphan_collection(test_client, test_store, tmp_path, monkeypatch):
    """`collections.create` commits, so a later failure would orphan the row.

    And an orphan is not merely untidy here: the name is UNIQUE and this route answers
    409 on a repeat, so the orphan would make that repo permanently un-ingestable — the
    retry can never get past the conflict it caused. The compensating delete is what
    keeps the request retryable.
    """
    from src.repositories import sqlite_store

    def boom(self, *a, **kw):
        raise RuntimeError("simulated enqueue failure")

    monkeypatch.setattr(sqlite_store.SQLiteJobRepository, "create", boom)

    with pytest.raises(RuntimeError, match="simulated"):
        test_client.post("/ingest/repo", json={"path": str(tmp_path), "name": "orphan-check"})

    # Nothing left behind...
    assert test_store.collections.get_by_path("orphan-check") is None

    # ...so the same name is genuinely ingestable once the fault clears.
    monkeypatch.undo()
    assert test_client.post(
        "/ingest/repo", json={"path": str(tmp_path), "name": "orphan-check"}).status_code == 202


def test_a_missing_directory_is_rejected_before_anything_is_written(test_client, test_store, tmp_path):
    resp = test_client.post("/ingest/repo", json={"path": "/nonexistent/xyz", "name": "nope"})
    assert resp.status_code == 400
    assert test_store.collections.get_by_path("nope") is None
