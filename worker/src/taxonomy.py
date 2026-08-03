# ABOUTME: Canonical taxonomy loader for the worker. Mirror of
# ABOUTME: orchestrator/src/pipeline/taxonomy.py; reads the SAME taxonomy.json.
"""The taxonomy is authored once at orchestrator/specs/taxonomy.json. The worker
image bundles a copy (Dockerfile COPYs it to /app/worker/taxonomy.json); in
dev/tests we read the orchestrator copy directly. Either way there is one
authored source — the classifier reference vocab and the layout anchors both
derive from it."""
from __future__ import annotations

import json
from pathlib import Path

_CANDIDATES = [
    Path("/app/worker/taxonomy.json"),  # bundled in the worker image
    Path(__file__).resolve().parents[2] / "orchestrator" / "specs" / "taxonomy.json",  # repo/dev/tests
]
_CACHE: dict | None = None


def _taxonomy_path() -> Path:
    for p in _CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError(f"taxonomy.json not found in {[str(p) for p in _CANDIDATES]}")


def load_taxonomy() -> dict:
    global _CACHE
    if _CACHE is None:
        _CACHE = json.loads(_taxonomy_path().read_text())
    return _CACHE


def anchor_paths(tax: dict | None = None) -> list[str]:
    tax = tax or load_taxonomy()
    return [f"{region}/{cat}/{topic}"
            for region, cats in tax.items()
            for cat, val in cats.items() if cat != "_desc"
            for topic in val[1]]


def reference_vocab_text(tax: dict | None = None) -> str:
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
