# ABOUTME: POST /charter writes an expert's declaration into the three existing slots.
# ABOUTME: Domain row, alias merge-map rows, and an authored spec — atomically.

import os
import pytest

os.environ.setdefault("AWS_ACCESS_KEY", "test-key")
os.environ.setdefault("AWS_SECRET_KEY", "test-secret")

CHARTER = {
    "domain": "business/legal-compliance/contracts",
    "aliases": ["Legal/Contracts", "contracts", "legal/agreements"],
    "spec": "# Contract extraction\nExtract Party, Obligation, Termination Trigger.",
}


def test_charter_creates_domain_row(test_client, test_store):
    r = test_client.post("/charter", json=CHARTER)
    assert r.status_code == 201
    domain = test_store.domains.get("business/legal-compliance/contracts")
    assert domain is not None
    assert domain.parent_path == "business/legal-compliance"


def test_charter_writes_lowercased_aliases(test_store, test_client):
    test_client.post("/charter", json=CHARTER)
    rows = dict(test_store.conn.execute(
        "SELECT from_label, to_path FROM domain_merge_map").fetchall())
    assert rows["legal/contracts"] == "business/legal-compliance/contracts"
    assert rows["contracts"] == "business/legal-compliance/contracts"
    assert "Legal/Contracts" not in rows, "aliases must be stored normalised"


def test_charter_alias_is_resolved_by_the_normalizer(test_store, test_client):
    """The whole point: a classifier inventing `legal/contracts` folds onto the canonical path."""
    from src.pipeline.domain_normalizer import normalize_domain_label
    test_client.post("/charter", json=CHARTER)
    assert normalize_domain_label(test_store, "legal/contracts") == \
        "business/legal-compliance/contracts"


def test_charter_writes_authored_spec(test_store, test_client):
    test_client.post("/charter", json=CHARTER)
    spec = test_store.specs.get_for_domain("business/legal-compliance/contracts")
    assert spec.source == "authored"
    assert spec.version == 1
    assert "Termination Trigger" in spec.spec_content


def test_charter_sets_spec_version_to_disable_auto_simmer(test_store, test_client):
    """ingest.py only queues simmer_domain when spec_version IS NULL. Setting it is how
    an authored spec is protected from being silently replaced."""
    test_client.post("/charter", json=CHARTER)
    assert test_store.domains.get("business/legal-compliance/contracts").spec_version == 1


def test_second_charter_bumps_the_version(test_store, test_client):
    test_client.post("/charter", json=CHARTER)
    revised = {**CHARTER, "spec": "# Revised\nExtract Party only."}
    r = test_client.post("/charter", json=revised)
    assert r.status_code == 201
    spec = test_store.specs.get_for_domain("business/legal-compliance/contracts")
    assert spec.version == 2
    assert spec.spec_content == "# Revised\nExtract Party only."


def test_alias_equal_to_the_domain_is_skipped(test_store, test_client):
    """A self-referential merge row would make normalize_domain_label loop back on itself."""
    test_client.post("/charter", json={
        **CHARTER, "aliases": ["business/legal-compliance/contracts"]})
    rows = test_store.conn.execute("SELECT COUNT(*) AS c FROM domain_merge_map").fetchone()["c"]
    assert rows == 0


def test_get_charter_returns_it(test_client):
    test_client.post("/charter", json=CHARTER)
    r = test_client.get("/charter", params={"domain": "business/legal-compliance/contracts"})
    assert r.status_code == 200
    body = r.json()
    assert body["domain"] == "business/legal-compliance/contracts"
    assert sorted(body["aliases"]) == ["contracts", "legal/agreements", "legal/contracts"]
    assert "Termination Trigger" in body["spec"]


def test_get_charter_404s_when_absent(test_client):
    r = test_client.get("/charter", params={"domain": "nope/nothing"})
    assert r.status_code == 404


def test_charter_returns_201_with_location(test_client):
    """Project convention, locked in by tests/test_rest_hygiene.py: creation endpoints
    return 201 Created with a Location header, not a bare 200."""
    r = test_client.post("/charter", json=CHARTER)
    assert r.status_code == 201
    assert r.headers.get("Location") == \
        "/charter?domain=business%2Flegal-compliance%2Fcontracts"
