# ABOUTME: The harness/metrics contract — frozen dataclasses that round-trip through JSON.
from charter_eval.models import DocResult, TypeResult

PAYLOAD = {
    "primary_domain": "business/legal-compliance/contracts",
    "secondary_domains": [],
    "confidence": 0.97,
    "run_general": False,
    "specs_applied": ["business/legal-compliance/contracts"],
    "entity_types": [
        {"type": "obligation", "count": 2,
         "examples": ["tenant — pay rent"], "names": ["tenant — pay rent", "tenant — pay rent"]},
        {"type": "clause", "count": 1, "examples": ["indemnification"], "names": ["indemnification"]},
    ],
}


def test_from_response_maps_every_field():
    d = DocResult.from_response("lease-01", "lease", True, "B", 0, 12.5, PAYLOAD)
    assert d.doc_id == "lease-01"
    assert d.instrument == "lease"
    assert d.executed is True
    assert d.variant == "B"
    assert d.run_general is False
    assert d.specs_applied == ("business/legal-compliance/contracts",)
    assert d.latency_s == 12.5
    assert d.names_for("obligation") == ("tenant — pay rent", "tenant — pay rent")
    assert d.names_for("clause") == ("indemnification",)


def test_names_for_absent_type_is_empty():
    d = DocResult.from_response("lease-01", "lease", True, "B", 0, 1.0, PAYLOAD)
    assert d.names_for("governing_law") == ()


def test_json_round_trip():
    d = DocResult.from_response("lease-01", "lease", True, "B", 0, 12.5, PAYLOAD)
    assert DocResult.from_dict(d.to_dict()) == d


def test_type_result_is_frozen():
    import dataclasses, pytest
    t = TypeResult(type="clause", count=1, names=("indemnification",))
    with pytest.raises(dataclasses.FrozenInstanceError):
        t.count = 2
