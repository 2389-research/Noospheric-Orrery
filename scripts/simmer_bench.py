# ABOUTME: Benchmark harness for the DECOMPOSED simmer flow (the local-run approach, run on cloud).
# ABOUTME: Wires the relay on_usage hook, runs discover->map->rules on a small chunk sample, dumps token/cost usage.
#
# Run from the worker dir so `src` + orrery_relay resolve:
#   cd worker && .venv/bin/python ../scripts/simmer_bench.py --domain business/marketing/branding --chunks 6 --iterations 1
#
# Backend/models come from the repo-root .env (ANTHROPIC_BACKEND=bedrock, CLASSIFICATION_MODEL, EXTRACTION_MODEL).

import argparse
import asyncio
import json
import shutil
import sys
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_dotenv():
    """Populate os.environ from repo-root .env (config reads os.environ; not auto-loaded outside Docker)."""
    import os
    env = REPO / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

from orrery_relay import Relay  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.db import get_connection  # noqa: E402
from src.jobs.simmer_general import (  # noqa: E402
    _discover_domain_types,
    _build_golden_set_mapreduce,
    _refine_spec_rules,
    BASE_TAXONOMY,
)

# Approx Bedrock USD per 1M tokens (input, output). Estimates — for relative comparison only.
PRICING = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

RECORDS = []


async def _record(event):
    RECORDS.append({
        "model": event.model,
        "input_tokens": event.input_tokens,
        "output_tokens": event.output_tokens,
        "latency_ms": event.latency_ms,
    })


def _install_usage_hook():
    """Make every Relay built via from_settings report into RECORDS."""
    orig = Relay.from_settings.__func__

    def patched(cls, settings, **kw):
        inst = orig(cls, settings, **kw)
        inst._on_usage = _record
        return inst

    Relay.from_settings = classmethod(patched)


def _summarize(wall_ms, phase_calls):
    by_model = {}
    total_cost = 0.0
    for r in RECORDS:
        m = r["model"]
        agg = by_model.setdefault(m, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
        agg["calls"] += 1
        agg["input_tokens"] += r["input_tokens"] or 0
        agg["output_tokens"] += r["output_tokens"] or 0
        pin, pout = PRICING.get(m, (0.0, 0.0))
        cost = (r["input_tokens"] or 0) / 1e6 * pin + (r["output_tokens"] or 0) / 1e6 * pout
        agg["cost_usd"] += cost
        total_cost += cost
    return {
        "arm": "decomposed",
        "wall_clock_s": round(wall_ms / 1000, 1),
        "total_calls": len(RECORDS),
        "total_input_tokens": sum(r["input_tokens"] or 0 for r in RECORDS),
        "total_output_tokens": sum(r["output_tokens"] or 0 for r in RECORDS),
        "total_cost_usd": round(total_cost, 4),
        "by_model": {m: {**v, "cost_usd": round(v["cost_usd"], 4)} for m, v in by_model.items()},
        "calls_per_phase": phase_calls,
    }


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True)
    ap.add_argument("--chunks", type=int, default=6)
    ap.add_argument("--iterations", type=int, default=1)
    ap.add_argument("--source-db", default=str(Path.home() / "orrery-data" / "orrery.db"))
    ap.add_argument("--out", default=str(REPO / "scratch_simmer_bench.json"))
    args = ap.parse_args()

    settings = get_settings()
    print(f"backend={settings.anthropic_backend} classify={settings.classification_model} extract={settings.extraction_model}", flush=True)
    if settings.anthropic_backend != "bedrock":
        print(f"WARNING: backend is {settings.anthropic_backend}, expected bedrock", flush=True)

    # Throwaway DB copy: discovery reads real entities; iteration writes land here, not the real DB.
    tmp_db = Path(args.out).with_suffix(".db")
    shutil.copy(args.source_db, tmp_db)
    job_id = str(uuid.uuid4())
    conn = get_connection(str(tmp_db))
    conn.execute(
        "INSERT INTO jobs (id, type, target, status, config) VALUES (?, 'simmer_domain', ?, 'running', ?)",
        (job_id, args.domain, json.dumps({"domain": args.domain})),
    )
    sample_chunks = conn.execute(
        """SELECT c.id, c.text, d.title FROM chunks c
           JOIN documents d ON c.document_id = d.id
           JOIN document_domains dd ON d.id = dd.document_id
           WHERE dd.domain_path = ? AND d.status IN ('classified','extracted','enriched')
           ORDER BY c.id LIMIT ?""",
        (args.domain, args.chunks),
    ).fetchall()
    conn.commit()
    conn.close()

    if not sample_chunks:
        print(f"No chunks for domain {args.domain}", flush=True)
        sys.exit(1)
    print(f"Sample: {len(sample_chunks)} chunks from {args.domain}", flush=True)

    _install_usage_hook()
    db = str(tmp_db)
    t0 = time.monotonic()
    phase_calls = {}

    # Phase 0: domain-specific type discovery (1 Sonnet call)
    n0 = len(RECORDS)
    domain_types = await _discover_domain_types(sample_chunks, args.domain, settings, db)
    phase_calls["discover"] = len(RECORDS) - n0
    n_types = len(domain_types.splitlines()) if domain_types else 0
    print(f"discovered {n_types} domain types", flush=True)
    taxonomy = domain_types if domain_types else BASE_TAXONOMY

    # Phase 1: golden set via map (one Haiku call per chunk)
    n1 = len(RECORDS)
    golden = await _build_golden_set_mapreduce(sample_chunks, settings, job_id, db, taxonomy=taxonomy)
    phase_calls["golden_map"] = len(RECORDS) - n1

    # Phase 2: rules-spec refinement loop (per-chunk Haiku extract + 1 Sonnet revise per iter)
    n2 = len(RECORDS)
    spec, score = await _refine_spec_rules(
        golden, sample_chunks, settings, job_id, db, args.iterations,
        domain_path=args.domain, taxonomy=taxonomy,
    )
    phase_calls["rules_loop"] = len(RECORDS) - n2

    wall_ms = (time.monotonic() - t0) * 1000
    summary = _summarize(wall_ms, phase_calls)
    summary.update({
        "domain": args.domain, "n_chunks": len(sample_chunks), "iterations": args.iterations,
        "n_domain_types": n_types, "final_f1_score": score,
        "spec_lines": len(spec.splitlines()),
    })

    Path(args.out).write_text(json.dumps({"summary": summary, "calls": RECORDS}, indent=2))
    Path(args.out + ".spec.md").write_text(spec)
    Path(args.out + ".golden.md").write_text(golden)
    print("\n=== USAGE SUMMARY ===", flush=True)
    print(json.dumps(summary, indent=2), flush=True)
    print(f"\nWrote {args.out} (+ .spec.md, .golden.md)", flush=True)
    tmp_db.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main())
