# ABOUTME: M6 needs hand-labelling, so the sampler must be deterministic (a re-run must
# ABOUTME: not invalidate labels already applied) and must read its own CSV back.
import csv
from charter_eval.models import DocResult, TypeResult
from charter_eval import sample


def doc(doc_id, **types):
    return DocResult(
        doc_id=doc_id, instrument="lease", executed=True, variant="B", repeat=0,
        primary_domain="business/legal-compliance/contracts", run_general=False,
        specs_applied=("business/legal-compliance/contracts",), latency_s=1.0,
        types=tuple(TypeResult(type=t, count=len(v), names=tuple(v)) for t, v in types.items()))


DOCS = [doc("a", obligation=[f"o{i}" for i in range(20)], clause=["c1", "c2"])]


def test_stratified_sample_caps_per_type():
    rows = sample.stratified_sample(DOCS, per_type=5, seed=42)
    by_type = {}
    for r in rows:
        by_type.setdefault(r["type"], []).append(r)
    assert len(by_type["obligation"]) == 5
    assert len(by_type["clause"]) == 2, "fewer than per_type available -> take all"
    assert all(r["correct"] == "" for r in rows)


def test_stratified_sample_is_deterministic():
    a = sample.stratified_sample(DOCS, per_type=5, seed=42)
    b = sample.stratified_sample(DOCS, per_type=5, seed=42)
    assert a == b


def test_precision_from_csv(tmp_path):
    p = tmp_path / "labels.csv"
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["doc_id", "type", "name", "correct"])
        w.writeheader()
        for name, correct in [("o1", "y"), ("o2", "y"), ("o3", "n"), ("o4", "y")]:
            w.writerow({"doc_id": "a", "type": "obligation", "name": name, "correct": correct})
        w.writerow({"doc_id": "a", "type": "clause", "name": "c1", "correct": "n"})
    assert sample.precision_from_csv(str(p), "obligation") == 0.75
    assert sample.precision_from_csv(str(p)) == 0.6


def test_unlabelled_rows_are_excluded(tmp_path):
    p = tmp_path / "labels.csv"
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["doc_id", "type", "name", "correct"])
        w.writeheader()
        w.writerow({"doc_id": "a", "type": "obligation", "name": "o1", "correct": "y"})
        w.writerow({"doc_id": "a", "type": "obligation", "name": "o2", "correct": ""})
    assert sample.precision_from_csv(str(p), "obligation") == 1.0
