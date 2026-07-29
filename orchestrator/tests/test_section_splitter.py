import pytest
from unittest.mock import AsyncMock
from src.pipeline.section_splitter import find_headings, find_font_headings, KNOWN_SECTIONS, label_sections


def test_finds_markdown_style_headings():
    text = "intro text\n\n## Introduction\n\nWe propose X.\n\n## Related Work\n\nPrior work Y.\n"
    headings = find_headings(text)
    sections = [h["section"] for h in headings]
    assert sections == ["introduction", "related_work"]


def test_finds_numbered_headings():
    text = "1. Introduction\nWe propose X.\n\n2. Related Work\nPrior work Y.\n\n3. Method\nOur approach.\n"
    headings = find_headings(text)
    assert [h["section"] for h in headings] == ["introduction", "related_work", "method"]


def test_finds_roman_numeral_headings_case_insensitive():
    text = "IV. EXPERIMENTS\nWe ran experiments.\n\nV. CONCLUSION\nWe conclude.\n"
    headings = find_headings(text)
    assert [h["section"] for h in headings] == ["experiments", "conclusion"]


def test_ignores_heading_keyword_inside_a_sentence():
    text = "This paper's introduction motivates the problem before the related work section.\n"
    headings = find_headings(text)
    assert headings == []


def test_headings_are_ascending_by_start_offset():
    text = "## Abstract\nA.\n\n## Method\nB.\n"
    headings = find_headings(text)
    assert headings[0]["start"] < headings[1]["start"]
    assert headings[0]["section"] == "abstract"


def test_known_sections_list_is_stable():
    assert KNOWN_SECTIONS == [
        "abstract", "introduction", "related_work", "method",
        "experiments", "conclusion",
    ]


@pytest.mark.asyncio
async def test_label_sections_covers_whole_document_no_headings():
    text = "word " * 50
    mock_relay = AsyncMock()
    mock_relay.complete_structured = AsyncMock(return_value={"section": "introduction"})
    spans = await label_sections(mock_relay, text, model="claude-haiku-4-5")
    assert spans[0]["start"] == 0
    assert spans[-1]["end"] == len(text)
    assert spans[0]["section"] == "introduction"
    mock_relay.complete_structured.assert_called_once()


@pytest.mark.asyncio
async def test_label_sections_splits_on_headings_no_llm_call_needed():
    text = "## Introduction\nWe propose X.\n\n## Method\nOur approach.\n"
    mock_relay = AsyncMock()
    mock_relay.complete_structured = AsyncMock()
    spans = await label_sections(mock_relay, text, model="claude-haiku-4-5")
    sections = [s["section"] for s in spans]
    assert sections == ["introduction", "method"]
    assert spans[0]["start"] == 0
    assert spans[-1]["end"] == len(text)
    # Consecutive spans are contiguous, no gaps/overlaps
    for prev, nxt in zip(spans, spans[1:]):
        assert prev["end"] == nxt["start"]
    mock_relay.complete_structured.assert_not_called()


def test_find_font_headings_matches_flagged_runs_against_keywords():
    font_runs = [
        {"start": 50, "end": 65, "text": "1 Introduction", "font_size": 12.0},
        {"start": 200, "end": 206, "text": "closed", "font_size": 10.0},  # not a section keyword
    ]
    headings = find_font_headings(font_runs)
    assert headings == [{"section": "introduction", "start": 50}]


@pytest.mark.asyncio
async def test_label_sections_merges_font_headings_not_caught_by_regex():
    # No blank-line-isolated heading here (regex alone finds nothing), but the
    # PDF's font metadata flags "1 Introduction" as a large-font run mid-text.
    text = "preamble text 1 Introduction body text continues here"
    font_runs = [{"start": 14, "end": 28, "text": "1 Introduction", "font_size": 12.0}]
    mock_relay = AsyncMock()
    mock_relay.complete_structured = AsyncMock(return_value={"section": "abstract"})
    spans = await label_sections(mock_relay, text, model="claude-haiku-4-5", font_runs=font_runs)
    sections = [s["section"] for s in spans]
    assert "introduction" in sections
    assert spans[0]["start"] == 0
    assert spans[-1]["end"] == len(text)


@pytest.mark.asyncio
async def test_label_sections_llm_fallback_for_text_before_first_heading():
    text = "Some preamble that has no heading.\n\n## Method\nOur approach.\n"
    mock_relay = AsyncMock()
    mock_relay.complete_structured = AsyncMock(return_value={"section": "abstract"})
    spans = await label_sections(mock_relay, text, model="claude-haiku-4-5")
    assert spans[0]["section"] == "abstract"
    assert spans[0]["start"] == 0
    assert spans[1]["section"] == "method"
    mock_relay.complete_structured.assert_called_once()
