# ABOUTME: Unit tests for the judge_matrix harness — pure logic only (no model calls).
# ABOUTME: Covers parse_cells and load_chunks, which are import-safe with no heavy deps.

import sys
import os
import importlib.util
from pathlib import Path

# Load judge_matrix by file path so it runs under the worker venv without needing
# the scripts/ dir on sys.path permanently.
_HARNESS = Path(__file__).resolve().parents[2] / "scripts" / "judge_matrix.py"
spec = importlib.util.spec_from_file_location("judge_matrix", _HARNESS)
judge_matrix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(judge_matrix)


def test_parse_cells():
    assert judge_matrix.parse_cells("1x1,1x3,2x1") == [(1, 1), (1, 3), (2, 1)]
    assert judge_matrix.parse_cells("2X2") == [(2, 2)]


def test_parse_cells_whitespace():
    # Whitespace around entries should be tolerated
    assert judge_matrix.parse_cells(" 1x1 , 3x2 ") == [(1, 1), (3, 2)]


def test_load_chunks(tmp_path):
    (tmp_path / "c1.txt").write_text("[Source: Doc A]\n\nhello world")
    (tmp_path / "c2.txt").write_text("plain text")
    chunks = judge_matrix.load_chunks(str(tmp_path))
    ids = {c[0] for c in chunks}
    assert ids == {"c1", "c2"}
    texts = {c[1] for c in chunks}
    assert "hello world" in " ".join(texts) and "plain text" in " ".join(texts)
    assert len(chunks) == 2


def test_load_chunks_source_header(tmp_path):
    """A [Source: ...] header is parsed for the title; the full file content is preserved as text."""
    (tmp_path / "chunk.txt").write_text("[Source: My Title]\n\nbody text here")
    chunks = judge_matrix.load_chunks(str(tmp_path))
    assert len(chunks) == 1
    cid, text, title = chunks[0]
    assert cid == "chunk"
    assert "body text here" in text
    assert title == "My Title"


def test_load_chunks_no_source_header(tmp_path):
    """Without a [Source: ...] header the title falls back to the filename stem."""
    (tmp_path / "raw_chunk.txt").write_text("no header here")
    chunks = judge_matrix.load_chunks(str(tmp_path))
    assert len(chunks) == 1
    cid, text, title = chunks[0]
    assert cid == "raw_chunk"
    assert title == "raw_chunk"
    assert "no header here" in text


def test_load_chunks_empty_dir(tmp_path):
    chunks = judge_matrix.load_chunks(str(tmp_path))
    assert chunks == []
