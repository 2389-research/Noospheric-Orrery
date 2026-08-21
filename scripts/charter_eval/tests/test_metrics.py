# ABOUTME: M1-M5 against hand-computed fixtures. M1 is the metric the A/B decision turns
# ABOUTME: on, so its edge cases (single doc, repeats of one doc) are pinned explicitly.
import pytest
from charter_eval.models import DocResult, TypeResult
from charter_eval import metrics


def doc(doc_id, variant="B", repeat=0, **types):
    return DocResult(
        doc_id=doc_id, instrument="lease", executed=True, variant=variant,
        repeat=repeat, primary_domain="business/legal-compliance/contracts",
        run_general=False, specs_applied=("business/legal-compliance/contracts",),
        latency_s=10.0,
        types=tuple(TypeResult(type=t, count=len(v), names=tuple(v))
                    for t, v in types.items()),
    )


# --- M1 mergeability -------------------------------------------------------

def test_mergeability_counts_names_shared_by_two_documents():
    docs = [
        doc("a", obligation=["tenant — pay rent", "tenant — insure"]),
        doc("b", obligation=["tenant — pay rent", "landlord — repair"]),
    ]
    # distinct: pay rent, insure, landlord repair = 3; shared by 2+ docs: pay rent = 1
    assert metrics.mergeability(docs, "obligation") == pytest.approx(1 / 3)


def test_mergeability_ignores_repeats_of_the_same_document():
    # The SAME doc_id run twice must not make a name look mergeable.
    docs = [
        doc("a", repeat=0, obligation=["tenant — pay rent"]),
        doc("a", repeat=1, obligation=["tenant — pay rent"]),
    ]
    assert metrics.mergeability(docs, "obligation") == 0.0


def test_mergeability_of_a_span_type_is_zero():
    docs = [
        doc("a", obligation=["tenant may renew this lease for five additional terms"]),
        doc("b", obligation=["if payment is not postmarked by the tenth day"]),
    ]
    assert metrics.mergeability(docs, "obligation") == 0.0


def test_mergeability_of_a_recurring_type_is_one():
    docs = [doc("a", clause=["indemnification"]), doc("b", clause=["indemnification"])]
    assert metrics.mergeability(docs, "clause") == 1.0


def test_mergeability_with_no_names_is_zero_not_an_error():
    assert metrics.mergeability([doc("a", clause=["x"])], "governing_law") == 0.0


# --- M2 name length --------------------------------------------------------

def test_median_name_words_uses_distinct_names():
    docs = [doc("a", obligation=["tenant — pay rent", "tenant — pay rent", "a b c d e f g"])]
    # distinct = ["tenant — pay rent" (3 words: the em-dash is a separator, not a word),
    #             "a b c d e f g" (7 words)] -> median (3+7)/2 = 5.0
    assert metrics.median_name_words(docs, "obligation") == pytest.approx(5.0)


def test_word_count_does_not_count_the_mandated_em_dash():
    # Variant B MANDATES "<party> — <duty>". Counting the em-dash would enforce the
    # frozen 6-word threshold as 5.
    assert metrics.word_count("tenant — pay rent") == 3
    assert metrics.word_count("tenant — pay rent within ten days") == 6


def test_a_six_word_b_name_passes_the_m2_threshold():
    from charter_eval import report
    docs = [doc("a", obligation=["tenant — pay rent within ten days"])]
    assert metrics.median_name_words(docs, "obligation") == pytest.approx(6.0)
    assert metrics.median_name_words(docs, "obligation") <= report.THRESHOLDS["m2_max_words"]


def test_word_count_of_an_unpunctuated_name_is_unchanged():
    assert metrics.word_count("a b c d e f g") == 7
    assert metrics.word_count("indemnification") == 1
    # a hyphenated word is one word; a standalone hyphen or en-dash is not a word
    assert metrics.word_count("tenant - pay one-year rent") == 4
    assert metrics.word_count("tenant – pay rent") == 3


def test_median_name_words_of_absent_type_is_zero():
    assert metrics.median_name_words([doc("a", clause=["x"])], "obligation") == 0.0


# --- M3 volume -------------------------------------------------------------

def test_volume_per_doc_averages_over_distinct_documents():
    docs = [
        doc("a", repeat=0, clause=["x", "y"]),
        doc("a", repeat=1, clause=["x", "y", "z"]),   # same doc, 2 repeats -> mean 2.5
        doc("b", repeat=0, clause=["x"]),             # -> 1.0
    ]
    assert metrics.volume_per_doc(docs, "clause") == pytest.approx((2.5 + 1.0) / 2)


def test_volume_and_cv_read_count_not_len_names():
    """M3/M5 must use TypeResult.count: `names` is empty without full_names=true."""
    def counted(repeat, n):
        return DocResult(
            doc_id="a", instrument="lease", executed=True, variant="B", repeat=repeat,
            primary_domain="business/legal-compliance/contracts", run_general=False,
            specs_applied=(), latency_s=1.0,
            types=(TypeResult(type="obligation", count=n, names=()),))

    one, two = counted(0, 5), counted(1, 15)
    assert metrics.volume_per_doc([one], "obligation") == pytest.approx(5.0)
    assert one.count_for("obligation") == 5 and one.names_for("obligation") == ()
    # counts 5 and 15 -> mean 10, population stddev 5 -> cv 0.5
    assert metrics.count_cv([one, two], "a", "obligation") == pytest.approx(0.5)


# --- M4 type stability ----------------------------------------------------

def test_type_stability_is_one_when_the_same_types_fire():
    docs = [doc("a", repeat=r, clause=["x"], obligation=["y"]) for r in (0, 1, 2)]
    assert metrics.type_stability(docs, "a") == 1.0


def test_type_stability_drops_when_a_type_goes_missing():
    docs = [
        doc("a", repeat=0, clause=["x"], obligation=["y"]),
        doc("a", repeat=1, clause=["x"]),
    ]
    # Jaccard({clause,obligation},{clause}) = 1/2
    assert metrics.type_stability(docs, "a") == pytest.approx(0.5)


def test_type_stability_of_a_single_run_is_one():
    assert metrics.type_stability([doc("a", clause=["x"])], "a") == 1.0


# --- M5 count variance ----------------------------------------------------

def test_count_cv_is_zero_for_identical_counts():
    docs = [doc("a", repeat=r, clause=["x", "y"]) for r in (0, 1)]
    assert metrics.count_cv(docs, "a", "clause") == 0.0


def test_count_cv_matches_hand_computation():
    docs = [
        doc("a", repeat=0, clause=["x"] * 15),
        doc("a", repeat=1, clause=["x"] * 17),
        doc("a", repeat=2, clause=["x"] * 19),
    ]
    # mean 17, population stddev = sqrt(8/3) ~= 1.63299 -> cv ~= 0.09606
    assert metrics.count_cv(docs, "a", "clause") == pytest.approx(0.09606, abs=1e-4)


def test_count_cv_of_absent_type_is_zero():
    docs = [doc("a", repeat=r, clause=["x"]) for r in (0, 1)]
    assert metrics.count_cv(docs, "a", "obligation") == 0.0


# --- M7 latency -----------------------------------------------------------

def test_mean_latency_averages_repeats_then_documents():
    docs = [doc("a", repeat=0, clause=["x"]), doc("a", repeat=1, clause=["x"]),
            doc("b", repeat=0, clause=["x"])]
    assert metrics.mean_latency_s(docs) == pytest.approx(10.0)
    assert metrics.mean_latency_s([]) == 0.0


# --- filtering ------------------------------------------------------------

def test_filter_variant_selects_one_arm():
    docs = [doc("a", variant="A", clause=["x"]), doc("a", variant="B", clause=["y"])]
    assert [d.variant for d in metrics.filter_variant(docs, "B")] == ["B"]
