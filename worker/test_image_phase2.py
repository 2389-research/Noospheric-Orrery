#!/usr/bin/env python
"""Test image simmer Phase 2 in isolation.

Uses an existing golden set from a previous Phase 1 run.
Runs Phase 2 only: evaluator + judges for N iterations.

Usage:
  docker exec -w /app/worker noospheric-orrery-worker-1 \
    uv run python /app/worker/test_image_phase2.py \
    --golden-set /data/specs/image_golden_set.md \
    --samples-dir /data/specs/image_samples \
    --iterations 2 \
    --db-path /data/workspaces/31e52a94/orrery.db
"""

import argparse
import asyncio
import json
import shlex
import uuid
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


async def run_phase2(args):
    from simmer_sdk import refine
    from src.config import get_settings
    from src.db import get_connection
    from src.jobs.simmer_general import _make_iteration_recorder

    settings = get_settings()

    golden_set_path = Path(args.golden_set)
    golden_text = golden_set_path.read_text()
    sample_dir = Path(args.samples_dir)
    specs_dir = Path(settings.specs_dir)
    specs_dir.mkdir(parents=True, exist_ok=True)

    # Provider config
    backend = settings.anthropic_backend
    provider_kwargs = {"api_provider": backend}
    if backend == "bedrock":
        provider_kwargs.update({
            "aws_access_key": settings.aws_access_key,
            "aws_secret_key": settings.aws_secret_key,
            "aws_region": settings.aws_region,
        })
    elif backend == "ollama":
        provider_kwargs["ollama_url"] = settings.ollama_url

    # Create a test job in DB
    job_id = str(uuid.uuid4())
    conn = get_connection(args.db_path)
    conn.execute(
        "INSERT INTO jobs (id, type, target, status) VALUES (?, 'simmer_image_phase2_test', 'general', 'running')",
        (job_id,),
    )
    conn.commit()
    conn.close()

    evaluator_script = Path(__file__).resolve().parent / "src" / "jobs" / "evaluate_image_spec.py"

    print(f"Phase 2 test — job {job_id}", flush=True)
    print(f"Golden set: {golden_set_path} ({len(golden_text)} chars)", flush=True)
    print(f"Samples: {sample_dir} ({len(list(sample_dir.glob('*.jpg')))} images)", flush=True)
    print(f"Iterations: {args.iterations}", flush=True)
    print(f"Evaluator: {evaluator_script}", flush=True)
    print(f"Models: judge={settings.classification_model} clerk={settings.classification_model} eval={settings.extraction_model}", flush=True)
    print("=" * 60, flush=True)

    spec_result = await refine(
        artifact=golden_text,
        criteria={
            "coverage": "When run on sample images, the spec captures all entities from the golden set",
            "description_quality": "Generated descriptions are accurate, specific, and useful for search",
            "generalizability": "The spec uses general visual observation rules — works on any image type",
            "precision": "No hallucinated entities or inaccurate descriptions",
        },
        primary="coverage",
        iterations=args.iterations,
        judge_mode="board",
        judge_panel=[
            {
                "name": "Coverage & Description Quality",
                "lens": (
                    "Read the eval-*/*.json files — these contain Haiku's extraction outputs per image. "
                    "Check entity coverage against the golden set. Check description quality. "
                    "Do NOT open image files directly."
                ),
            },
            {
                "name": "Precision & Generalizability",
                "lens": (
                    "Read the eval-*/*.json files AND the spec itself. "
                    "Are extracted entities grounded? Does the spec use general rules or hardcoded names? "
                    "Would it work on travel photos, not just these samples?"
                ),
            },
        ],
        output_dir=specs_dir / "image_spec_test",
        generator_model=settings.classification_model,
        judge_model=settings.classification_model,
        clerk_model=settings.classification_model,
        evaluator=(
            f"uv run python {shlex.quote(str(evaluator_script))}"
            f" --candidate {{candidate_path}}"
            f" --samples-dir {shlex.quote(str(sample_dir))}"
            f" --golden-set {shlex.quote(str(golden_set_path))}"
            f" --output-dir {{output_dir}}"
            f" --iteration {{iteration}}"
        ),
        background=(
            f"This spec will be executed by Haiku to extract entities and descriptions from images.\n"
            f"Golden set: {golden_text[:2000]}\n\n"
            f"The evaluator runs the spec against sample images using Haiku each iteration.\n"
            f"Raw extraction results are in eval-N/ directories as JSON files.\n"
            f"DO NOT open image files. Read eval-N/*.json for Haiku's observations.\n"
            f"Score based on whether Haiku's extractions match the golden set."
        ),
        on_iteration=_make_iteration_recorder(job_id, "extraction_spec", args.db_path, str(specs_dir / "image_spec_test")),
        **provider_kwargs,
    )

    print("=" * 60, flush=True)
    print(f"Phase 2 complete — best score: {spec_result.composite}/10", flush=True)
    print(f"Best candidate length: {len(spec_result.best_candidate)} chars", flush=True)

    # Mark job completed
    conn = get_connection(args.db_path)
    conn.execute("UPDATE jobs SET status = 'completed' WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Test image simmer Phase 2 in isolation")
    parser.add_argument("--golden-set", required=True, help="Path to golden set from Phase 1")
    parser.add_argument("--samples-dir", required=True, help="Directory of sample images")
    parser.add_argument("--iterations", type=int, default=2, help="Number of iterations")
    parser.add_argument("--db-path", required=True, help="Path to workspace DB")
    args = parser.parse_args()
    asyncio.run(run_phase2(args))


if __name__ == "__main__":
    main()
