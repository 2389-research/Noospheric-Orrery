# ABOUTME: Benchmark harness for the AGENTIC simmer flow (simmer-sdk refine + ClaudeSDKClient board judging).
# ABOUTME: Runs the golden-set refinement on the SAME chunk sample as simmer_bench.py; reads refine().total_usage.
#
#   cd worker && .venv/bin/python ../scripts/agentic_bench.py --domain business/marketing/branding --chunks 5 --iterations 1
#
# Mirrors the pre-decomposition (commit 3671254) golden phase: refine(judge_mode="board", all-Sonnet) on bedrock.

import argparse
import asyncio
import json
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_dotenv():
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

from simmer_sdk import refine  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.db import get_connection  # noqa: E402


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True)
    ap.add_argument("--chunks", type=int, default=5)
    ap.add_argument("--iterations", type=int, default=1)
    ap.add_argument("--source-db", default=str(Path.home() / "orrery-data" / "orrery.db"))
    ap.add_argument("--out", default=str(REPO / "scratch_agentic_bench.json"))
    args = ap.parse_args()

    settings = get_settings()
    model = settings.classification_model  # all-Sonnet, like the old agentic path
    print(f"backend={settings.anthropic_backend} model={model} (agentic/board)", flush=True)

    conn = get_connection(args.source_db)
    rows = conn.execute(
        """SELECT c.id, c.text, d.title FROM chunks c
           JOIN documents d ON c.document_id = d.id
           JOIN document_domains dd ON d.id = dd.document_id
           WHERE dd.domain_path = ? AND d.status IN ('classified','extracted','enriched')
           ORDER BY c.id LIMIT ?""",
        (args.domain, args.chunks),
    ).fetchall()
    conn.close()
    if not rows:
        print(f"No chunks for {args.domain}")
        return
    print(f"Sample: {len(rows)} chunks from {args.domain} (deterministic by id)", flush=True)

    work = Path(args.out + ".work")
    sample_dir = work / "samples"
    sample_dir.mkdir(parents=True, exist_ok=True)
    for r in rows:
        (sample_dir / f"{r[0]}.txt").write_text(f"[Source: {r[2]}]\n\n{r[1]}")

    seed = work / "seed.md"
    seed.write_text(
        "# Golden Set\n\n## Entity Type Taxonomy\n"
        "Discover the entity types that matter for these documents.\n\n"
        "## Reference Entities\n\n"
        "Read every sample document and list ALL entities you find as a JSON array of "
        '{"name": "lowercase name", "type": "EntityType"}. Every entity must appear in at '
        "least one sample document.\n"
    )

    provider_kwargs = {
        "api_provider": "bedrock",
        "aws_access_key": settings.aws_access_key,
        "aws_secret_key": settings.aws_secret_key,
        "aws_region": settings.aws_region,
    }

    t0 = time.monotonic()
    result = await refine(
        artifact=str(seed),
        criteria={
            "coverage": "The reference entity list contains every named entity in the sample documents",
            "precision": "Every entity in the list actually appears in at least one sample document",
            "taxonomy_quality": "Entity types are meaningful, consistent, and correctly assigned",
        },
        primary="coverage",
        iterations=args.iterations,
        judge_mode="board",
        judge_panel=[
            {"name": "Coverage & Depth", "lens": "Cross-reference the reference list against the docs. Flag missing entities; the list must be exhaustive."},
            {"name": "Precision & Quality", "lens": "Verify each entity appears in a doc and has the correct type. Flag hallucinations and mistyped entities."},
        ],
        output_dir=work / "golden_out",
        generator_model=model,
        judge_model=model,
        clerk_model=model,
        background=(
            f"Sample chunks are in {sample_dir}. Read ALL of them. The golden set must contain "
            f"(1) an entity type taxonomy and (2) a JSON array of EVERY entity found in the chunks. "
            f"Be thorough — this is the ground truth extraction specs are tested against."
        ),
        **provider_kwargs,
    )
    wall_ms = (time.monotonic() - t0) * 1000

    usage = result.usage.to_dict() if getattr(result, "usage", None) else {}
    summary = {
        "arm": "agentic",
        "phase": "golden_set",
        "domain": args.domain,
        "n_chunks": len(rows),
        "iterations": args.iterations,
        "wall_clock_s": round(wall_ms / 1000, 1),
        "total_calls": usage.get("total_calls"),
        "total_input_tokens": usage.get("total_input_tokens"),
        "total_output_tokens": usage.get("total_output_tokens"),
        "total_cost_usd": usage.get("estimated_cost_usd"),
        "by_role": usage.get("by_role"),
        "by_model": usage.get("by_model"),
        "best_iteration": result.best_iteration,
        "candidate_chars": len(result.best_candidate or ""),
    }
    Path(args.out).write_text(json.dumps({"summary": summary, "total_usage": usage}, indent=2))
    Path(args.out + ".candidate.md").write_text(result.best_candidate or "")
    print("\n=== AGENTIC USAGE SUMMARY (golden phase) ===", flush=True)
    print(json.dumps(summary, indent=2), flush=True)
    print(f"\nWrote {args.out} (+ .candidate.md)", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
