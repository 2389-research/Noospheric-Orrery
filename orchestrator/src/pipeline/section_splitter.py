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
