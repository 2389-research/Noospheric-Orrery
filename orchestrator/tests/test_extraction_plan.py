# ABOUTME: resolve_extraction_plan decides which domain specs run and whether the
# ABOUTME: general pass runs. An authored spec is complete, so it suppresses general.

import os
import pytest

os.environ.setdefault("AWS_ACCESS_KEY", "test-key")
os.environ.setdefault("AWS_SECRET_KEY", "test-secret")

from src.db import init_db
from src.repositories.sqlite_store import SQLiteDataStore
from src.pipeline.extraction_plan import resolve_extraction_plan


@pytest.fixture
def store(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    s = SQLiteDataStore(db_path)
    yield s
    s.close()


def test_no_specs_runs_general_only(store):
    run_general, specs = resolve_extraction_plan(store, ["legal/contracts"])
    assert run_general is True
    assert specs == []


def test_simmered_spec_still_runs_general(store):
    store.specs.create("s1", "legal/contracts", 1, "domain content", source="simmered")
    run_general, specs = resolve_extraction_plan(store, ["legal/contracts"])
    assert run_general is True
    assert [s.id for s in specs] == ["s1"]


def test_authored_spec_suppresses_general(store):
    store.specs.create("s1", "legal/contracts", 1, "domain content", source="authored")
    run_general, specs = resolve_extraction_plan(store, ["legal/contracts"])
    assert run_general is False
    assert [s.id for s in specs] == ["s1"]


def test_authored_spec_at_ancestor_applies_and_suppresses(store):
    store.specs.create("s1", "legal", 1, "ancestor content", source="authored")
    run_general, specs = resolve_extraction_plan(store, ["legal/contracts/nda"])
    assert run_general is False
    assert [s.id for s in specs] == ["s1"]


def test_authored_primary_with_simmered_secondary(store):
    """The authored spec suppresses the GENERAL pass, not other domain specs."""
    store.specs.create("s1", "legal/contracts", 1, "authored", source="authored")
    store.specs.create("s2", "business/finance", 1, "simmered", source="simmered")
    run_general, specs = resolve_extraction_plan(
        store, ["legal/contracts", "business/finance"])
    assert run_general is False
    assert {s.id for s in specs} == {"s1", "s2"}


def test_specs_are_deepest_first(store):
    store.specs.create("s_shallow", "legal", 1, "shallow", source="simmered")
    store.specs.create("s_deep", "legal/contracts", 1, "deep", source="simmered")
    _, specs = resolve_extraction_plan(store, ["legal/contracts"])
    assert [s.id for s in specs] == ["s_deep", "s_shallow"]


def test_a_spec_shared_by_two_domains_is_not_run_twice(store):
    store.specs.create("s1", "legal", 1, "shared", source="simmered")
    _, specs = resolve_extraction_plan(store, ["legal/contracts", "legal/ip"])
    assert [s.id for s in specs] == ["s1"]


def test_latest_version_wins(store):
    store.specs.create("s1", "legal/contracts", 1, "v1", source="simmered")
    store.specs.create("s2", "legal/contracts", 2, "v2", source="authored")
    run_general, specs = resolve_extraction_plan(store, ["legal/contracts"])
    assert run_general is False
    assert [s.id for s in specs] == ["s2"]
