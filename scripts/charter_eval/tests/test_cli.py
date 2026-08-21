# ABOUTME: CLI behaviour for the `report` subcommand: it must score ONE arm, refuse a
# ABOUTME: mixed results file rather than average the arms, and surface M7 latency.
import csv

from charter_eval import harness, report
from charter_eval.__main__ import main
from charter_eval.models import DocResult, TypeResult


def doc(doc_id, variant, names, latency_s=100.0):
    return DocResult(
        doc_id=doc_id, instrument="lease", executed=True, variant=variant, repeat=0,
        primary_domain="business/legal-compliance/contracts", run_general=False,
        specs_applied=("business/legal-compliance/contracts",), latency_s=latency_s,
        types=(TypeResult(type="obligation", count=len(names), names=tuple(names)),))


def _results(tmp_path, docs, name="results.jsonl"):
    p = tmp_path / name
    harness.save(docs, str(p))
    return str(p)


def _labels(tmp_path, rows):
    p = tmp_path / "labels.csv"
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["doc_id", "type", "name", "correct"])
        w.writeheader()
        w.writerows(rows)
    return str(p)


def test_report_refuses_a_mixed_variant_file(tmp_path, capsys):
    path = _results(tmp_path, [doc("a", "A", ["tenant — pay rent"]),
                               doc("a", "B", ["tenant — pay rent"])])
    rc = main(["report", "--results", path])
    err = capsys.readouterr().err
    assert rc != 0
    assert "A" in err and "B" in err and "--variant" in err


def test_report_variant_filters_before_deciding(tmp_path, capsys):
    long_name = "tenant may renew this lease for five additional successive terms"
    docs = [doc("a", "B", ["tenant — pay rent"]), doc("b", "B", ["tenant — pay rent"]),
            doc("a", "v1", [long_name]), doc("b", "v1", [long_name])]
    path = _results(tmp_path, docs)
    labels = _labels(tmp_path, [{"doc_id": "a", "type": "obligation",
                                 "name": "tenant — pay rent", "correct": "y"}])
    rc = main(["report", "--results", path, "--variant", "B",
               "--precision-csv", labels])
    out = capsys.readouterr().out
    assert rc == 0
    assert "variant: B" in out
    assert "(2 results)" in out
    assert "SHIP B" in out


def test_report_on_a_single_variant_file_needs_no_flag(tmp_path, capsys):
    path = _results(tmp_path, [doc("a", "B", ["tenant — pay rent"])])
    rc = main(["report", "--results", path])
    out = capsys.readouterr().out
    assert rc == 0
    assert "variant: B" in out


def test_report_prints_mean_latency_per_document(tmp_path, capsys):
    docs = [doc("a", "B", ["tenant — pay rent"], latency_s=100.0),
            doc("b", "B", ["tenant — pay rent"], latency_s=140.0)]
    rc = main(["report", "--results", _results(tmp_path, docs)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "M7 latency: 120.0s per document" in out


def test_report_prints_insufficient_data_not_a_verdict(tmp_path, capsys):
    docs = [DocResult(
        doc_id="a", instrument="lease", executed=True, variant="B", repeat=0,
        primary_domain="business/legal-compliance/contracts", run_general=False,
        specs_applied=(), latency_s=1.0,
        types=(TypeResult(type="obligation", count=0, names=()),))]
    labels = _labels(tmp_path, [{"doc_id": "a", "type": "obligation",
                                 "name": "x", "correct": "y"}])
    rc = main(["report", "--results", _results(tmp_path, docs),
               "--precision-csv", labels])
    out = capsys.readouterr().out
    assert rc == 0
    assert report.INSUFFICIENT_DATA in out
    assert "SHIP" not in out


def test_sample_per_type_default_is_twenty_five(tmp_path, capsys):
    """M6 is judged against 0.80; 10 labels can only express multiples of 0.10."""
    import inspect
    from charter_eval import sample
    assert inspect.signature(sample.stratified_sample).parameters["per_type"].default == 25

    docs = [doc("a", "B", [f"tenant — duty {i}" for i in range(40)])]
    out = tmp_path / "sample.csv"
    rc = main(["sample", "--results", _results(tmp_path, docs), "--out", str(out)])
    capsys.readouterr()
    assert rc == 0
    with open(out, newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 25, "the CLI default must match the library default"
