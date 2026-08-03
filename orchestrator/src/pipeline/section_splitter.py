# ABOUTME: Splits a research paper's full text into section-labeled spans.
# ABOUTME: Heuristic heading detection with an LLM fallback for unclassified stretches.

import re

KNOWN_SECTIONS = ["abstract", "introduction", "related_work", "method", "experiments", "conclusion", "references"]

_SECTION_KEYWORDS = {
    "abstract": ["abstract"],
    "introduction": ["introduction"],
    "related_work": ["related work", "background"],
    "method": ["method", "methods", "methodology", "approach"],
    "experiments": ["experiments", "experiment", "results", "evaluation"],
    "conclusion": ["conclusion", "conclusions", "discussion", "limitations"],
    "references": ["references", "bibliography"],
}

# Sections never worth extracting entities from — citation lists are noise, not
# paper content. Callers should skip these spans entirely rather than run
# extraction against them (see extractor.extract_document_sectioned).
SKIP_SECTIONS = {"references"}

# Matches a whole line that is *only* a heading: optional markdown hashes, optional
# numbering (arabic "1." or roman "IV."), then the keyword phrase, nothing else after it.
_NUMBERING = r"(?:#{1,3}\s*|\d+(?:\.\d+)*\.?\s+|[IVXLC]+\.\s+)?"


def _build_line_pattern(keyword: str) -> re.Pattern:
    return re.compile(rf"^\s*{_NUMBERING}{re.escape(keyword)}\s*$", re.IGNORECASE)


# Looser than _build_line_pattern: matches the keyword as a PREFIX rather than the
# whole line, so "6 Discussion and Limitations" still matches "discussion". Only
# used against font-flagged runs (already narrowed to large/bold text), so the
# looser anchor doesn't risk matching a keyword mid-sentence in regular body text.
def _build_prefix_pattern(keyword: str) -> re.Pattern:
    return re.compile(rf"^\s*{_NUMBERING}{re.escape(keyword)}\b", re.IGNORECASE)


# A numbered/lettered heading-shaped line ("3 The OpenVLA Model", "A Data Mixture
# Details") that doesn't match any known section keyword. Font-flagging already
# narrows candidates to large/bold text, so this only needs to rule out plain
# prose — a short line starting with a numbering marker qualifies.
_HEADING_SHAPE = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?\s+|[A-Z]\s+|[IVXLC]+\.\s+)\S")
_MAX_HEADING_LENGTH = 60


def find_headings(text: str) -> list[dict]:
    headings = []
    offset = 0
    for line in text.split("\n"):
        line_start = offset
        offset += len(line) + 1  # account for the '\n' split removed
        stripped = line.strip()
        if not stripped:
            continue
        for section, keywords in _SECTION_KEYWORDS.items():
            for keyword in keywords:
                if _build_line_pattern(keyword).match(stripped):
                    headings.append({"section": section, "start": line_start})
                    break
            else:
                continue
            break
    headings.sort(key=lambda h: h["start"])
    return headings


def find_font_headings(font_runs: list[dict]) -> list[dict]:
    """Like find_headings, but matches against pre-identified large/bold-font
    text runs (see file_extractor.extract_text_with_font_runs) instead of
    scanning every line — catches headings whose formatting signals size but
    whose text doesn't sit alone on its own extracted line.

    Two tiers: a run matching a known section keyword (even with trailing
    words, e.g. "Discussion and Limitations") gets that section directly. A
    run that's merely heading-shaped (numbered/lettered, short) but matches no
    known keyword — a paper-specific section name like "The OpenVLA Model" —
    still becomes a boundary, with section=None so label_sections routes that
    (now much smaller) span to the LLM fallback instead of it being silently
    absorbed into whichever preceding section's span runs longest."""
    headings = []
    for run in font_runs:
        stripped = run["text"].strip()
        matched_section = None
        for section, keywords in _SECTION_KEYWORDS.items():
            for keyword in keywords:
                if _build_prefix_pattern(keyword).match(stripped):
                    matched_section = section
                    break
            if matched_section:
                break
        if matched_section:
            headings.append({"section": matched_section, "start": run["start"]})
        elif len(stripped) <= _MAX_HEADING_LENGTH and _HEADING_SHAPE.match(stripped):
            headings.append({"section": None, "start": run["start"]})
    headings.sort(key=lambda h: h["start"])
    return headings


_CLASSIFY_PROMPT = """Which section of a research paper does the following text most likely belong to?

Choose exactly one: abstract, introduction, related_work, method, experiments, conclusion, references, other

TEXT:
{excerpt}"""

_CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "section": {
            "type": "string",
            "enum": KNOWN_SECTIONS + ["other"],
        },
    },
    "required": ["section"],
}


async def _classify_span(relay, text: str, model: str) -> str:
    excerpt = text[:1500]
    result = await relay.complete_structured(
        model=model, max_tokens=64,
        messages=[{"role": "user", "content": _CLASSIFY_PROMPT.format(excerpt=excerpt)}],
        schema=_CLASSIFY_SCHEMA,
        tool_name="classify_section",
        tool_description="Classify which research paper section a text excerpt belongs to",
    )
    section = result.get("section", "other")
    return section if section in KNOWN_SECTIONS else "unclassified"


async def label_sections(relay, text: str, model: str, font_runs: list[dict] | None = None) -> list[dict]:
    headings = find_headings(text)
    if font_runs:
        seen_starts = {h["start"] for h in headings}
        for h in find_font_headings(font_runs):
            if h["start"] not in seen_starts:
                headings.append(h)
                seen_starts.add(h["start"])
        headings.sort(key=lambda h: h["start"])
    doc_len = len(text)

    # Build raw spans between consecutive headings (and before the first / there are none)
    boundaries = [h["start"] for h in headings] + [doc_len]
    raw_spans = []
    if not headings:
        raw_spans.append({"section": None, "start": 0, "end": doc_len})
    else:
        if headings[0]["start"] > 0:
            raw_spans.append({"section": None, "start": 0, "end": headings[0]["start"]})
        for i, heading in enumerate(headings):
            raw_spans.append({
                "section": heading["section"],
                "start": heading["start"],
                "end": boundaries[i + 1],
            })

    spans = []
    for span in raw_spans:
        if span["section"] is None:
            span_text = text[span["start"]:span["end"]]
            span["section"] = await _classify_span(relay, span_text, model) if span_text.strip() else "unclassified"
        spans.append(span)
    return spans
