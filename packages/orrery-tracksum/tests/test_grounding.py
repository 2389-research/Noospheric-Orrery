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


def test_a_suffix_after_a_known_extension_is_not_grounded_by_its_prefix():
    """`\\b` accepted the boundary before a dot, so `src/store.js` in the trace marked
    the INVENTED `src/store.js.bak` as grounded — defeating the one thing this check
    exists to catch. The prefix must not stand in for the whole token."""
    g = check_grounding("wrote src/store.js.bak", TRACE)
    assert "src/store.js" not in g["grounded_paths"] if "grounded_paths" in g else True
    # The invented artifact must not be counted as grounded.
    assert g["grounded"] == 0, f"a .bak suffix was grounded by its prefix: {g}"


def test_a_terminal_sentence_dot_is_not_part_of_the_path():
    assert paths_in("wrote src/store.js.") == {"src/store.js"}
    assert paths_in("ran src/store.js, then stopped") == {"src/store.js"}


def test_extensionless_and_newly_covered_artifacts_are_seen():
    """`workflow.dip`, CI yaml and extensionless files are what tracker runs name.
    An extension-only pattern was blind to them, so a summary could invent a Dockerfile
    and the check would report nothing."""
    text = "touched workflow.dip, .github/workflows/ci.yml, Dockerfile and pyproject.toml"
    found = paths_in(text)
    assert "workflow.dip" in found
    assert ".github/workflows/ci.yml" in found
    assert "Dockerfile" in found
    assert "pyproject.toml" in found


def test_an_invented_dockerfile_is_flagged():
    g = check_grounding("wrote Dockerfile", TRACE)
    assert g["ungrounded"] == ["Dockerfile"]
