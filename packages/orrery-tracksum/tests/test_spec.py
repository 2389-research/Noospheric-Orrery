from orrery_tracksum import gather_spec, working_dir_of
from orrery_tracksum.spec import SPEC_ARTIFACTS


def test_concatenation_order_is_broad_to_specific(tmp_path):
    """Pinned: the tuple's order IS the output. Reordering changes every `text` and so
    every `fingerprint`, which would make corpora summarized under different orders
    incomparable."""
    assert SPEC_ARTIFACTS == ("BRIEF.md", "SPEC.md", ".flagship/CONTRACT.md",
                              ".flagship/UNIT-SPECS.md")
    (tmp_path / "BRIEF.md").write_text("BRIEF")
    (tmp_path / "SPEC.md").write_text("SPEC")
    flagship = tmp_path / ".flagship"
    flagship.mkdir()
    (flagship / "CONTRACT.md").write_text("CONTRACT")
    (flagship / "UNIT-SPECS.md").write_text("UNITS")

    text = gather_spec(str(tmp_path))["text"]
    assert text == "BRIEF\n\nSPEC\n\nCONTRACT\n\nUNITS"
    # `artifacts` is sorted for stable reporting, so it does NOT match the text order
    assert gather_spec(str(tmp_path))["artifacts"] == [
        ".flagship/CONTRACT.md", ".flagship/UNIT-SPECS.md", "BRIEF.md", "SPEC.md"]


def test_working_dir_is_everything_above_the_tracker_dir():
    run_dir = "/home/me/flagship-r0/.tracker/runs/run-123"
    assert working_dir_of(run_dir) == "/home/me/flagship-r0"


def test_working_dir_of_a_plain_path_is_unchanged():
    assert working_dir_of("/home/me/somewhere") == "/home/me/somewhere"


def test_gather_spec_collects_present_artifacts_with_text_embedded(tmp_path):
    (tmp_path / "SPEC.md").write_text("# spec\nproduct requirements\n")
    flagship = tmp_path / ".flagship"
    flagship.mkdir()
    (flagship / "CONTRACT.md").write_text("# contract\npinned literals\n")

    spec = gather_spec(str(tmp_path))
    assert spec["artifacts"] == [".flagship/CONTRACT.md", "SPEC.md"]
    # text is EMBEDDED, not referenced — the bundle has to be readable from inside a
    # container that never sees the original checkout
    assert "product requirements" in spec["text"]
    assert "pinned literals" in spec["text"]
    assert spec["chars"] == len(spec["text"])
    assert len(spec["fingerprint"]) == 16


def test_fingerprint_distinguishes_perturbed_specs(tmp_path):
    """The fingerprint is what makes two runs in a chain comparable: same fingerprint
    means the same problem statement, different means the spec was perturbed."""
    a = tmp_path / "a"
    a.mkdir()
    (a / "SPEC.md").write_text("same text")
    b = tmp_path / "b"
    b.mkdir()
    (b / "SPEC.md").write_text("same text")
    c = tmp_path / "c"
    c.mkdir()
    (c / "SPEC.md").write_text("different text")

    assert gather_spec(str(a))["fingerprint"] == gather_spec(str(b))["fingerprint"]
    assert gather_spec(str(a))["fingerprint"] != gather_spec(str(c))["fingerprint"]


def test_no_spec_artifacts_yields_empty_fingerprint(tmp_path):
    spec = gather_spec(str(tmp_path))
    assert spec == {"artifacts": [], "chars": 0, "text": "", "fingerprint": None}
