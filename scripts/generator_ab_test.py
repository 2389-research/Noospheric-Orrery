# ABOUTME: A/B test the spec-phase generator FRAMING on a real (spec, ASI) round from a prior run.
# ABOUTME: Same spec + same judge ASI, two reviser prompts (rewrite vs surgical) → extract → compare F1/FP/change.
#
#   cd worker && .venv/bin/python ../scripts/generator_ab_test.py

import asyncio, difflib, os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.environ["ANTHROPIC_BACKEND"] = "ollama"
os.environ["CLASSIFICATION_MODEL"] = "gemma4:26b"
os.environ["EXTRACTION_MODEL"] = "gemma4:e4b"
os.environ["OLLAMA_URL"] = "http://localhost:11434"

from orrery_relay import Relay  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.db import get_connection  # noqa: E402
import re  # noqa: E402
from src.jobs.simmer_general import (  # noqa: E402
    _parse_golden_keys, _strip_fences, SPEC_EXTRACT_PROMPT, GOLDEN_MAP_SCHEMA, SPEC_REVISE_ASI_PROMPT,
    GOLDEN_MAP_PROMPT,
)

DOMAIN = "business/technology/multi_agent_systems"
DB = str(REPO / "data/local/workspaces/default/orrery.db")

# NEW prod framing (surgical) = SPEC_REVISE_ASI_PROMPT (imported, just swapped in simmer_general).
# OLD framing (broad rewrite) — hardcoded here so we can A/B it against the new prod prompt.
REWRITE_PROMPT = """You are refining a GENERALIZED entity-extraction SPEC (a reusable prompt that must work on documents it has never seen). You are NOT extracting entities and you MUST NOT list specific entity names in the spec.{domain_note}

Current spec:
---
{spec}
---

Highest-leverage improvement to make (ASI) — from a judge that reviewed how this spec actually performed when run:
{asi}

Rewrite the spec's type definitions and INCLUDE/EXCLUDE rules to apply this improvement — GENERALLY,
by describing the PATTERN, not by naming specific entities (e.g. "EXCLUDE vague descriptors like
'quality'", "INCLUDE single-word domain fields", "extract multi-word names whole, not fragments").
Keep a few ILLUSTRATIVE examples, but the body must be RULES, never a list of answer-key entities.

Return the full revised spec (markdown). No commentary."""


async def revise(relay, settings, spec, asi, prompt_template):
    resp = await relay.complete(
        model=settings.classification_model, max_tokens=4096,
        messages=[{"role": "user", "content": prompt_template.format(domain_note="", spec=spec, asi=asi)}])
    return _strip_fences(resp.text) or spec


async def evaluate(relay, settings, spec, chunks, golden):
    extracted = set()
    for c in chunks:
        try:
            res = await relay.complete_structured(
                model=settings.extraction_model, max_tokens=2048,
                messages=[{"role": "user", "content": SPEC_EXTRACT_PROMPT.format(spec=spec, chunk=c[1])}],
                schema=GOLDEN_MAP_SCHEMA, tool_name="extract_entities", tool_description="Extract entities per the spec")
            for e in (res.get("entities", []) if isinstance(res, dict) else []):
                n = str(e.get("name", "")).lower().strip(); t = str(e.get("type", "")).strip().lower()
                if n: extracted.add((n, t))
        except Exception as ex:
            print(f"    extract err: {ex}", flush=True)
    hits = extracted & golden
    prec = len(hits) / len(extracted) if extracted else 0.0
    rec = len(hits) / len(golden) if golden else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return dict(f1=f1, prec=prec, rec=rec, ext=len(extracted), fp=len(extracted - golden), miss=len(golden - extracted))


async def main():
    settings = get_settings()
    relay = Relay.from_settings(settings)
    conn = get_connection(DB)
    spec = conn.execute("SELECT spec_content FROM specs WHERE domain_path=? ORDER BY version DESC LIMIT 1", (DOMAIN,)).fetchone()[0]
    golden_md = conn.execute("SELECT golden_set FROM specs WHERE domain_path=? ORDER BY version DESC LIMIT 1", (DOMAIN,)).fetchone()[0]
    asi = conn.execute("SELECT asi FROM simmer_iterations WHERE phase='extraction_spec' AND asi!='' ORDER BY iteration DESC LIMIT 1").fetchone()[0]
    chunks = conn.execute(
        """SELECT c.id, c.text FROM chunks c JOIN documents d ON c.document_id=d.id
           JOIN document_domains dd ON d.id=dd.document_id WHERE dd.domain_path=? ORDER BY c.id LIMIT 10""", (DOMAIN,)).fetchall()
    conn.close()

    # Build the golden over THESE SAME chunks (the stored golden came from a different random
    # sample, so it can't be matched against extraction over this fixed set). Map per chunk with
    # the domain taxonomy parsed from the stored golden, so golden + extraction share one corpus.
    m = re.search(r"## Entity Type Taxonomy\n(.*?)\n\n", golden_md, re.DOTALL)
    taxonomy = m.group(1).strip() if m else ""
    golden_set = set()
    for c in chunks:
        try:
            res = await relay.complete_structured(
                model=settings.extraction_model, max_tokens=2048,
                messages=[{"role": "user", "content": GOLDEN_MAP_PROMPT.format(tax=taxonomy, exclude="", chunk=c[1])}],
                schema=GOLDEN_MAP_SCHEMA, tool_name="extract_entities", tool_description="Extract named entities")
            for e in (res.get("entities", []) if isinstance(res, dict) else []):
                n = str(e.get("name", "")).lower().strip(); t = str(e.get("type", "")).strip().lower()
                if n: golden_set.add((n, t))
        except Exception as ex:
            print(f"  golden-build err: {ex}", flush=True)
    golden = golden_set
    print(f"spec={len(spec)} chars, {len(spec.splitlines())} lines | golden(rebuilt on these chunks)={len(golden)} | {len(chunks)} chunks")
    print(f"ASI: {asi[:200]}...\n")

    N = 3
    print("=== baseline (current spec, no edit) ===", flush=True)
    base = await evaluate(relay, settings, spec, chunks, golden)
    print(f"  F1={base['f1']:.2f} prec={base['prec']:.2f} rec={base['rec']:.2f} ext={base['ext']} fp={base['fp']}\n")

    def mean(xs):
        return sum(xs) / len(xs) if xs else 0.0

    for name, tmpl in [("REWRITE (old framing)", REWRITE_PROMPT), ("SURGICAL (new prod framing)", SPEC_REVISE_ASI_PROMPT)]:
        print(f"=== {name} — {N} runs ===", flush=True)
        runs = []
        for k in range(N):
            revised = await revise(relay, settings, spec, asi, tmpl)
            changed = sum(1 for d in difflib.unified_diff(spec.splitlines(), revised.splitlines()) if d and d[0] in "+-" and not d.startswith(("+++", "---")))
            m = await evaluate(relay, settings, revised, chunks, golden)
            runs.append((changed, m))
            print(f"  run {k+1}: {changed} lines changed | F1={m['f1']:.2f} prec={m['prec']:.2f} rec={m['rec']:.2f} ext={m['ext']} fp={m['fp']}", flush=True)
        print(f"  MEAN: lines_changed={mean([c for c,_ in runs]):.1f}  F1={mean([m['f1'] for _,m in runs]):.2f}  "
              f"prec={mean([m['prec'] for _,m in runs]):.2f}  rec={mean([m['rec'] for _,m in runs]):.2f}  "
              f"fp={mean([m['fp'] for _,m in runs]):.1f}\n", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
