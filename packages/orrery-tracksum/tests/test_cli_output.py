"""The CLI writes bundle files named from corpus-controlled data.

`run_label` comes out of the corpus, so for filesystem use it is untrusted: `../name`
escapes `--out`, an absolute value makes `os.path.join` discard `--out` entirely, and two
runs sharing a label silently overwrote each other's bundle — losing a run with no error.
The ingest side already validated labels; the PRODUCER did not, which left the gap open
at the source.
"""
import argparse
import sys

import pytest

from orrery_tracksum.cli import _safe_filename, main


def _bundle(label: str, n: int) -> dict:
    """A bundle with the fields `build_index` reads, plus a payload marker."""
    return {
        "run_label": label, "rung": "R0", "nodes": [],
        "dip": {"recognized": ""}, "coherency": {"completeness_pass": True},
        "n": n,
    }


@pytest.mark.parametrize("label,forbidden", [
    ("../escape", ".."),
    ("../../etc/passwd", ".."),
    ("/absolute/path", "/"),
    ("nested/dir/name", "/"),
    ("back\\slash", "\\"),
    (".", None),
    ("..", None),
])
def test_a_hostile_label_cannot_escape_the_output_directory(label, forbidden):
    name = _safe_filename(label)
    assert "/" not in name and "\\" not in name, f"{label!r} -> {name!r} still traverses"
    assert name not in (".", ".."), f"{label!r} -> {name!r} names a directory"
    assert name, "must always yield a usable filename"


def test_a_normal_label_is_left_recognisable():
    assert _safe_filename("R6-brief") == "R6-brief"
    assert _safe_filename("run_1.2") == "run_1.2"


def test_an_empty_or_missing_label_still_yields_a_filename():
    assert _safe_filename("") == "run"
    assert _safe_filename(None) == "run"
    assert _safe_filename("///") == "run"


def test_the_model_flag_works_after_the_subcommand(monkeypatch):
    """The usage this module's own docstring documents.

    `--model` was registered only on the top-level parser, so
    `... runs <dir> --model gemma4:26b` exited with SystemExit 2 — the documented
    command did not run.
    """
    # Parse only; do not execute the command.
    import orrery_tracksum.cli as cli

    called = {}

    def _spy(a):
        called["model"] = a.model
        return 0

    # monkeypatch, not assignment: leaking a stub over module state let a LATER test
    # call the spy instead of the production command.
    monkeypatch.setattr(cli, "_cmd_runs", _spy)
    assert main(["runs", "/tmp/corpus", "--model", "gemma4:e4b"]) == 0
    assert called["model"] == "gemma4:e4b"


def test_the_model_flag_still_works_before_the_subcommand(monkeypatch):
    """Both positions must work — the old form is in scripts and muscle memory."""
    import orrery_tracksum.cli as cli

    called = {}

    def _spy(a):
        called["model"] = a.model
        return 0

    monkeypatch.setattr(cli, "_cmd_runs", _spy)
    assert main(["--model", "qwen3.5:9b", "runs", "/tmp/corpus"]) == 0
    assert called["model"] == "qwen3.5:9b", (
        "a subparser default overwrote the value given before the subcommand")


def test_a_label_colliding_with_a_generated_suffix_does_not_overwrite(tmp_path, monkeypatch):
    """Counting per BASE name was not enough.

    Labels `foo`, `foo`, `foo~2` produced `foo`, `foo~2`, `foo~2` — the third silently
    overwriting the second, which is the exact loss the suffix exists to prevent. Every
    emitted name has to be tracked, not just the base.
    """
    import json
    import types

    import orrery_tracksum.cli as cli

    bundles = [_bundle("foo", 1), _bundle("foo", 2), _bundle("foo~2", 3)]

    out = tmp_path / "out"
    a = types.SimpleNamespace(out=str(out), root="x", model="m", distill_path=None)

    # Exercise only the writing block, with the summarization stubbed out.
    # monkeypatch throughout: assigning over module state leaked stubs into later tests.
    monkeypatch.setattr(cli, "summarize_runs", lambda *args, **kw: bundles)
    monkeypatch.setattr(cli, "distill_reader",
                        lambda d: types.SimpleNamespace(find_runs=lambda root: ["r"]))
    monkeypatch.setattr(cli, "_relay", lambda model: (lambda *a, **k: None))
    # setitem, not sys.modules.setdefault: a permanent entry made a LATER test's result
    # depend on this one having run first — order-dependent tests hide real breakage.
    monkeypatch.setitem(sys.modules, "distill", types.ModuleType("distill"))

    cli._cmd_runs(a)

    written = sorted(p.name for p in out.iterdir() if p.name != "index.json")
    assert len(written) == 3, f"a bundle was overwritten: {written}"
    payloads = sorted(json.loads((out / n).read_text())["n"] for n in written)
    assert payloads == [1, 2, 3], "every run's payload must survive"


def test_the_index_names_the_file_that_was_actually_written(tmp_path, monkeypatch):
    """The index must point at the emitted filename, not a reconstructed one.

    The writer sanitises and de-duplicates names, so `<run_label>.json` is a GUESS: a
    collision-resolved `foo~2.json` was unreachable and `foo.json` was read twice, which
    means the de-duplication fix silently lost a run instead of overwriting it. Recording
    the emitted name is what closes that loop.
    """
    import json
    import types

    import orrery_tracksum.cli as cli

    bundles = [_bundle("foo", 1), _bundle("foo", 2), _bundle("../escape", 3)]
    out = tmp_path / "out"
    a = types.SimpleNamespace(out=str(out), root="x", model="m", distill_path=None)

    monkeypatch.setattr(cli, "summarize_runs", lambda *args, **kw: bundles)
    monkeypatch.setattr(cli, "distill_reader",
                        lambda d: types.SimpleNamespace(find_runs=lambda root: ["r"]))
    monkeypatch.setattr(cli, "_relay", lambda model: (lambda *a, **k: None))
    # Installed here too, not inherited from a sibling test. Relying on another test to
    # have populated sys.modules is exactly the order dependence being removed — and it
    # showed up immediately: run alone, this test failed with ModuleNotFoundError.
    monkeypatch.setitem(sys.modules, "distill", types.ModuleType("distill"))

    cli._cmd_runs(a)

    index = json.loads((out / "index.json").read_text())
    assert len(index) == 3
    for row in index:
        assert (out / row["file"]).is_file(), (
            f"index names {row['file']!r}, which was never written")
    # And every payload is reachable exactly once.
    seen = sorted(json.loads((out / row["file"]).read_text())["n"] for row in index)
    assert seen == [1, 2, 3]
