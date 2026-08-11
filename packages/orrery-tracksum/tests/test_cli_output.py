"""The CLI writes bundle files named from corpus-controlled data.

`run_label` comes out of the corpus, so for filesystem use it is untrusted: `../name`
escapes `--out`, an absolute value makes `os.path.join` discard `--out` entirely, and two
runs sharing a label silently overwrote each other's bundle — losing a run with no error.
The ingest side already validated labels; the PRODUCER did not, which left the gap open
at the source.
"""
import argparse

import pytest

from orrery_tracksum.cli import _safe_filename, main


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


def test_the_model_flag_works_after_the_subcommand():
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

    cli._cmd_runs = _spy
    assert main(["runs", "/tmp/corpus", "--model", "gemma4:e4b"]) == 0
    assert called["model"] == "gemma4:e4b"


def test_the_model_flag_still_works_before_the_subcommand():
    """Both positions must work — the old form is in scripts and muscle memory."""
    import orrery_tracksum.cli as cli

    called = {}

    def _spy(a):
        called["model"] = a.model
        return 0

    cli._cmd_runs = _spy
    assert main(["--model", "qwen3.5:9b", "runs", "/tmp/corpus"]) == 0
    assert called["model"] == "qwen3.5:9b", (
        "a subparser default overwrote the value given before the subcommand")
