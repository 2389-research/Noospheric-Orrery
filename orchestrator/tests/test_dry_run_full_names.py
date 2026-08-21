# ABOUTME: The dry-run truncates examples to 3, which makes cross-document mergeability
# ABOUTME: uncomputable. `full_names=true` opts into the untruncated list.
import io
import pytest
from unittest.mock import patch


def _upload(client, body: bytes, *, full_names: bool):
    url = "/ingest?dry_run=true" + ("&full_names=true" if full_names else "")
    return client.post(url, files={"file": ("c.txt", io.BytesIO(body), "text/plain")})


FAKE_ENTITIES = [
    {"name": "tenant — pay monthly rent", "type": "obligation"},
    {"name": "tenant — maintain insurance", "type": "obligation"},
    {"name": "tenant — pay monthly rent", "type": "obligation"},  # duplicate on purpose
    {"name": "tenant — surrender premises", "type": "obligation"},
    {"name": "indemnification", "type": "clause"},
]


@pytest.fixture
def stub_pipeline():
    with patch("src.routes.ingest.classify_document") as clf, \
         patch("src.routes.ingest.extract_document") as ext:
        async def _clf(**kw):
            return {"primary_domain": "business/legal-compliance/contracts",
                    "secondary_domains": [], "confidence": 0.9}
        async def _ext(**kw):
            return list(FAKE_ENTITIES)
        clf.side_effect = _clf
        ext.side_effect = _ext
        yield


def test_names_absent_by_default(test_client, stub_pipeline):
    r = _upload(test_client, b"lease text " * 50, full_names=False)
    assert r.status_code == 200
    by_type = {t["type"]: t for t in r.json()["entity_types"]}
    assert by_type["obligation"]["count"] == 4
    assert by_type["obligation"]["examples"] == [
        "tenant — pay monthly rent",
        "tenant — maintain insurance",
        "tenant — surrender premises",
    ], "examples stay deduped and capped at 3"
    assert by_type["obligation"]["names"] == [], "names must be opt-in"


def test_full_names_returns_every_name_including_duplicates(test_client, stub_pipeline):
    r = _upload(test_client, b"lease text " * 50, full_names=True)
    assert r.status_code == 200
    by_type = {t["type"]: t for t in r.json()["entity_types"]}
    names = by_type["obligation"]["names"]
    assert len(names) == 4, "not deduplicated — count and names must agree"
    assert names.count("tenant — pay monthly rent") == 2
    assert by_type["clause"]["names"] == ["indemnification"]


def test_full_names_does_not_change_the_other_fields(test_client, stub_pipeline):
    plain = _upload(test_client, b"lease text " * 50, full_names=False).json()
    full = _upload(test_client, b"lease text " * 50, full_names=True).json()
    for key in ("primary_domain", "secondary_domains", "run_general", "specs_applied"):
        assert plain[key] == full[key]
