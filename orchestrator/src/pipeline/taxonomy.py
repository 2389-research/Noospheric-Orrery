# ABOUTME: Single source of truth for the domain taxonomy. The classifier's
# ABOUTME: reference vocabulary AND the layout anchors both derive from here.
"""Canonical taxonomy loader.

`specs/taxonomy.json` is the one authoritative list of `region/category/topic`
domains (software + business + product + operations + people + research). Both
consumers read from it so they never drift:
  - the classifier renders its REFERENCE VOCABULARY from `reference_vocab_text()`
  - the UMAP layout anchors come from `anchor_paths()`

Shape: {region: {"_desc": str, category: [description, [topic, ...]]}}.
Edit the JSON to add/expand categories — the prompt and the anchors both update.
The classifier is still told it MAY invent a new topic/category when nothing fits.
"""
from __future__ import annotations

import json
from pathlib import Path

_TAXONOMY_PATH = Path(__file__).resolve().parent.parent.parent / "specs" / "taxonomy.json"
_CACHE: dict | None = None


def load_taxonomy(path: Path | None = None) -> dict:
    global _CACHE
    if path is not None:
        return json.loads(Path(path).read_text())
    if _CACHE is None:
        _CACHE = json.loads(_TAXONOMY_PATH.read_text())
    return _CACHE


def anchor_paths(tax: dict | None = None) -> list[str]:
    """Flat `region/category/topic` list — the UMAP layout anchors."""
    tax = tax or load_taxonomy()
    return [f"{region}/{cat}/{topic}"
            for region, cats in tax.items()
            for cat, val in cats.items() if cat != "_desc"
            for topic in val[1]]


def reference_vocab_text(tax: dict | None = None) -> str:
    """Render the classifier's REFERENCE VOCABULARY block, grouped by region."""
    tax = tax or load_taxonomy()
    lines: list[str] = []
    for region, cats in tax.items():
        rdesc = cats.get("_desc")
        if rdesc:
            lines.append(f"\n# {region} — {rdesc}")
        for cat, val in cats.items():
            if cat == "_desc":
                continue
            desc, topics = val[0], val[1]
            lines.append(f"{region}/{cat} — {desc}: {', '.join(topics)}")
    return "\n".join(lines).strip()
