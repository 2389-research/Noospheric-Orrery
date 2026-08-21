# ABOUTME: The pre-registered A/B rule. These thresholds are frozen by the design doc;
# ABOUTME: a diff here is a deliberate protocol change, not a tweak.
import pytest
from charter_eval.models import DocResult, TypeResult
from charter_eval import report


def doc(doc_id, names, variant="B"):
    return DocResult(
        doc_id=doc_id, instrument="lease", executed=True, variant=variant, repeat=0,
        primary_domain="business/legal-compliance/contracts", run_general=False,
        specs_applied=("business/legal-compliance/contracts",), latency_s=10.0,
        types=(TypeResult(type="obligation", count=len(names), names=tuple(names)),))


def test_thresholds_are_the_pre_registered_values():
    assert report.THRESHOLDS == {"m1_min": 0.30, "m2_max_words": 6.0, "m6_min": 0.80}


def test_ships_b_when_all_three_pass():
    docs = [doc("a", ["tenant — pay rent", "tenant — insure"]),
            doc("b", ["tenant — pay rent", "tenant — insure"])]
    d = report.decide(docs, precision_b=0.9)
    assert d.ship == "B"
    assert d.m1 == pytest.approx(1.0)
    # the em-dash separator is not a word: "tenant — insure" is 2, "tenant — pay rent" is 3
    assert d.m2 == pytest.approx(2.5)


def test_ships_a_when_mergeability_is_too_low():
    docs = [doc("a", ["tenant — pay rent"]), doc("b", ["landlord — repair roof"])]
    d = report.decide(docs, precision_b=0.9)
    assert d.ship == "A"
    assert any("m1" in r for r in d.reasons)


def test_ships_a_when_names_are_too_long():
    long_a = "tenant may renew this lease for five additional successive one-year terms"
    docs = [doc("a", [long_a]), doc("b", [long_a])]
    d = report.decide(docs, precision_b=0.95)
    assert d.ship == "A"
    assert any("m2" in r for r in d.reasons)


def test_ships_a_when_precision_collapses():
    docs = [doc("a", ["tenant — pay rent"]), doc("b", ["tenant — pay rent"])]
    d = report.decide(docs, precision_b=0.5)
    assert d.ship == "A"
    assert any("m6" in r for r in d.reasons)


def test_reasons_list_every_failure_not_just_the_first():
    long_a = "tenant may renew this lease for five additional successive one-year terms"
    docs = [doc("a", [long_a]), doc("b", ["landlord — repair roof"])]
    d = report.decide(docs, precision_b=0.1)
    assert len(d.reasons) == 3


def test_boundary_values_pass():
    """m1 exactly 0.30, m2 exactly 6.0, m6 exactly 0.80 must all PASS (>=, <=, >=)."""
    shared = [f"s{i} b c d e f" for i in range(3)]      # 6 words each, in BOTH docs
    unique = [f"u{i} b c d e f" for i in range(7)]      # 6 words each, only in doc a
    docs = [doc("a", shared + unique), doc("b", shared)]
    d = report.decide(docs, precision_b=0.80)
    assert d.m1 == pytest.approx(0.30), "3 shared of 10 distinct"
    assert d.m2 == pytest.approx(6.0)
    assert d.ship == "B", "thresholds are inclusive; boundary must not fail"
    assert d.reasons == ()


def test_boundary_fixture_has_no_punctuation_so_the_word_rule_cannot_move_it():
    """The boundary fixture's names are unpunctuated, so M2 stays exactly 6.0."""
    from charter_eval import metrics
    assert metrics.word_count("s0 b c d e f") == 6
    assert metrics.word_count("u0 b c d e f") == 6


# --- insufficient data ----------------------------------------------------

def test_no_documents_is_insufficient_data_not_ship_a():
    d = report.decide([], precision_b=0.9)
    assert d.ship == report.INSUFFICIENT_DATA
    assert d.ship != "A"
    assert any("no obligation names" in r for r in d.reasons)


def test_all_obligation_names_absent_is_insufficient_data():
    empty = DocResult(
        doc_id="a", instrument="lease", executed=True, variant="B", repeat=0,
        primary_domain="business/legal-compliance/contracts", run_general=False,
        specs_applied=(), latency_s=1.0,
        types=(TypeResult(type="clause", count=3, names=("indemnification",)),
               TypeResult(type="obligation", count=0, names=()),))
    d = report.decide([empty], precision_b=0.9)
    assert d.ship == report.INSUFFICIENT_DATA


def test_a_genuine_low_mergeability_result_still_ships_a():
    docs = [doc("a", ["tenant — pay rent"]), doc("b", ["landlord — repair roof"])]
    d = report.decide(docs, precision_b=0.9)
    assert d.ship == "A"
    assert any(r.startswith("m1") for r in d.reasons)


# --- reason precision -----------------------------------------------------

def test_m1_reason_does_not_read_as_a_contradiction(monkeypatch):
    monkeypatch.setattr(report.metrics, "mergeability", lambda docs, t: 0.2999)
    d = report.decide([doc("a", ["tenant — pay rent"])], precision_b=0.9)
    reason = next(r for r in d.reasons if r.startswith("m1"))
    assert "0.30 < 0.3" not in reason
    assert reason == "m1 mergeability 0.2999 < 0.3000"


# --- render_table ---------------------------------------------------------

def test_render_table_reports_m4_and_m5_and_labels_the_aggregation():
    docs = [doc("a", ["tenant — pay rent"]), doc("b", ["tenant — pay rent"])]
    out = report.render_table(docs, ["obligation", "clause"])
    assert "M4 type stability" in out
    assert "mean over documents" in out
    assert "M5 cv" in out
    assert "obligation" in out and "clause" in out


def test_render_table_does_not_raise_on_a_type_absent_everywhere():
    out = report.render_table([doc("a", ["tenant — pay rent"])], ["governing_law"])
    assert "governing_law" in out


def test_render_table_on_no_documents_does_not_raise():
    assert "documents: 0" in report.render_table([], ["obligation"])
