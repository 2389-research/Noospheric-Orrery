# ABOUTME: Harness tests with a fake transport. No live LLM in pytest, ever.
import json
import pytest
from charter_eval import harness

MANIFEST = {
    "documents": [
        {"doc_id": "lease-01", "path": "/tmp/lease-01.txt", "instrument": "lease", "executed": True},
        {"doc_id": "nda-01", "path": "/tmp/nda-01.txt", "instrument": "nda", "executed": True},
    ]
}


def _payload(names):
    return {
        "primary_domain": "business/legal-compliance/contracts",
        "secondary_domains": [], "confidence": 0.97,
        "run_general": False,
        "specs_applied": ["business/legal-compliance/contracts"],
        "entity_types": [{"type": "obligation", "count": len(names),
                          "examples": names[:3], "names": names}],
    }


def test_manifest_load(tmp_path):
    p = tmp_path / "corpus.json"
    p.write_text(json.dumps(MANIFEST))
    m = harness.Manifest.load(str(p))
    assert [e.doc_id for e in m.entries] == ["lease-01", "nda-01"]
    assert m.entries[0].instrument == "lease"
    assert m.entries[0].executed is True


def test_collect_calls_transport_once_per_doc_per_repeat(tmp_path):
    p = tmp_path / "corpus.json"
    p.write_text(json.dumps(MANIFEST))
    calls = []

    def fake(file_path):
        calls.append(file_path)
        return _payload(["tenant — pay rent"]), 1.5

    docs = harness.collect(harness.Manifest.load(str(p)), "B", repeats=3, transport=fake)
    assert len(calls) == 6, "2 documents x 3 repeats"
    assert len(docs) == 6
    assert sorted({d.repeat for d in docs}) == [0, 1, 2]
    assert {d.variant for d in docs} == {"B"}
    assert docs[0].latency_s == 1.5
    assert docs[0].instrument == "lease"


def test_collect_records_the_failure_and_continues(tmp_path):
    p = tmp_path / "corpus.json"
    p.write_text(json.dumps(MANIFEST))

    def flaky(file_path):
        if "nda" in file_path:
            raise RuntimeError("422 unsupported")
        return _payload(["tenant — pay rent"]), 1.0

    docs, errors = harness.collect_with_errors(
        harness.Manifest.load(str(p)), "B", repeats=1, transport=flaky)
    assert len(docs) == 1
    assert len(errors) == 1
    assert errors[0]["doc_id"] == "nda-01"
    assert "422" in errors[0]["error"]


def test_save_load_round_trip(tmp_path):
    p = tmp_path / "corpus.json"
    p.write_text(json.dumps(MANIFEST))
    docs = harness.collect(harness.Manifest.load(str(p)), "B", repeats=1,
                           transport=lambda f: (_payload(["a b"]), 1.0))
    out = tmp_path / "results.jsonl"
    harness.save(docs, str(out))
    assert harness.load(str(out)) == docs


def test_http_transport_builds_the_dry_run_url():
    t = harness.HttpTransport("http://localhost:8000")
    assert t.url == "http://localhost:8000/ingest?dry_run=true&full_names=true"
