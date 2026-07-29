from src.pipeline.section_splitter import find_headings, KNOWN_SECTIONS


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
