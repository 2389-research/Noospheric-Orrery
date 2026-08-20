# ABOUTME: Refining an authored spec must preserve the authored CONTRACT.
# ABOUTME: A refined spec stored as 'simmered' would silently re-enable the general pass.

import os
import pytest

os.environ.setdefault("AWS_ACCESS_KEY", "test-key")
os.environ.setdefault("AWS_SECRET_KEY", "test-secret")

from src.db import init_db, get_connection
from src.jobs.simmer_domain import _build_seed_content, _authored_spec_for


def _db_with_authored_spec(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO specs (id, domain_path, version, spec_content, source) "
        "VALUES ('s1', 'legal/contracts', 1, '# My rules\nExtract Party and Obligation.', 'authored')")
    conn.commit()
    return db_path, conn


def test_authored_spec_is_detected(tmp_path):
    _, conn = _db_with_authored_spec(tmp_path)
    assert _authored_spec_for(conn, "legal/contracts") == \
        "# My rules\nExtract Party and Obligation."
    conn.close()


def test_no_authored_spec_returns_none(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO specs (id, domain_path, version, spec_content, source) "
        "VALUES ('s1', 'legal/contracts', 1, 'simmered content', 'simmered')")
    conn.commit()
    assert _authored_spec_for(conn, "legal/contracts") is None
    conn.close()


def test_authored_seed_uses_the_users_rules_and_says_complete(tmp_path):
    seed = _build_seed_content(
        "legal/contracts", general_spec=None, authored_spec="# My rules\nExtract Party.")
    assert "# My rules" in seed
    assert "Extract Party." in seed
    assert "COMPLETE" in seed, "the seed must state the complete (non-additive) contract"
    assert "Add entity types specific to" not in seed, "must not use the additive framing"


def test_unauthored_seed_keeps_the_additive_framing(tmp_path):
    seed = _build_seed_content(
        "legal/contracts", general_spec="GENERAL SPEC BODY", authored_spec=None)
    assert "GENERAL SPEC BODY" in seed
    assert "Add entity types specific to legal/contracts" in seed
