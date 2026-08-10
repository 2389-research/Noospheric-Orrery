from orrery_tracksum import check_grounding, paths_in

TRACE = """NODE BuildStore
ran: node --test src/store.js
wrote src/store.js and test/store.test.mjs
read .flagship/gate/001.log
"""


def test_paths_in_finds_file_tokens():
    assert paths_in(TRACE) == {"src/store.js", "test/store.test.mjs", ".flagship/gate/001.log"}


def test_grounded_summary_reports_no_hallucinations():
    summary = "WHAT IT DID: wrote src/store.js, then ran its tests in test/store.test.mjs."
    g = check_grounding(summary, TRACE)
    assert g == {"named": 2, "grounded": 2, "ungrounded": []}


def test_invented_path_is_flagged():
    """The check that makes a small model usable at scale — not "does it read well"
    but "did it invent an artifact"."""
    summary = "WHAT IT DID: wrote src/store.js and src/evaluator.js."
    g = check_grounding(summary, TRACE)
    assert g["ungrounded"] == ["src/evaluator.js"]
    assert g["grounded"] == 1


def test_ungrounded_is_sorted_for_stable_output():
    summary = "wrote zeta.js and alpha.js"
    assert check_grounding(summary, TRACE)["ungrounded"] == ["alpha.js", "zeta.js"]
