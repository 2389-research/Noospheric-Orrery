# ABOUTME: Splits a research paper's full text into section-labeled spans.
# ABOUTME: Heuristic heading detection with an LLM fallback for unclassified stretches.

import re

KNOWN_SECTIONS = ["abstract", "introduction", "related_work", "method", "experiments", "conclusion"]

_SECTION_KEYWORDS = {
    "abstract": ["abstract"],
    "introduction": ["introduction"],
    "related_work": ["related work", "background"],
    "method": ["method", "methods", "methodology", "approach"],
    "experiments": ["experiments", "experiment", "results", "evaluation"],
    "conclusion": ["conclusion", "conclusions", "discussion", "limitations"],
}

# Matches a whole line that is *only* a heading: optional markdown hashes, optional
# numbering (arabic "1." or roman "IV."), then the keyword phrase, nothing else after it.
_NUMBERING = r"(?:#{1,3}\s*|\d+(?:\.\d+)*\.?\s+|[IVXLC]+\.\s+)?"


def _build_line_pattern(keyword: str) -> re.Pattern:
    return re.compile(rf"^\s*{_NUMBERING}{re.escape(keyword)}\s*$", re.IGNORECASE)


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


_CLASSIFY_PROMPT = """Which section of a research paper does the following text most likely belong to?

Choose exactly one: abstract, introduction, related_work, method, experiments, conclusion, other

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


async def label_sections(relay, text: str, model: str) -> list[dict]:
    headings = find_headings(text)
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
