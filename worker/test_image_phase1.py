#!/usr/bin/env python
"""Test image simmer Phase 1 in isolation — 2 iterations."""

import argparse
import asyncio
import base64
import shlex
import uuid
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


async def run_phase1(args):
    from simmer_sdk import refine
    from orrery_relay import Relay
    from src.config import get_settings
    from src.db import get_connection
    from src.jobs.simmer_general import SEED_IMAGE_GOLDEN_SET, _make_iteration_recorder

    settings = get_settings()
    relay = Relay.from_settings(settings)

    specs_dir = Path(settings.specs_dir)
    sample_dir = Path(args.samples_dir)
    prescan_dir = specs_dir / "image_prescans"
    prescan_dir.mkdir(parents=True, exist_ok=True)

    # Provider config
    backend = settings.anthropic_backend
    provider_kwargs = {"api_provider": backend}
    if backend == "bedrock":
        provider_kwargs.update({
            "aws_access_key": settings.aws_access_key,
            "aws_secret_key": settings.aws_secret_key,
            "aws_region": settings.aws_region,
        })

    # Job tracking
    job_id = str(uuid.uuid4())
    conn = get_connection(args.db_path)
    conn.execute(
        "INSERT INTO jobs (id, type, target, status) VALUES (?, 'test_image_phase1', 'general', 'running')",
        (job_id,),
    )
    conn.commit()
    conn.close()

    # Pre-scan images with Haiku
    images = sorted(f for f in sample_dir.iterdir() if f.suffix.lower() in {".jpg", ".jpeg", ".png"})
    print(f"Phase 1 test — {len(images)} images, {args.iterations} iterations", flush=True)
    print(f"Pre-scanning with Haiku...", flush=True)

    for old in prescan_dir.glob("*"):
        old.unlink()

    for img_file in images:
        try:
            b64 = base64.b64encode(img_file.read_bytes()).decode()
            suffix = img_file.suffix.lower()
            media_type = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
            prescan = await relay.complete_structured(
                model=settings.extraction_model,
                max_tokens=2048,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": "Describe everything visible. List all entities, materials, colors, techniques, settings."},
                ]}],
                schema={
                    "type": "object",
                    "properties": {
                        "entities": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "type": {"type": "string"}}, "required": ["name", "type"]}},
                        "description": {"type": "string"},
                        "details": {"type": "string"},
                    },
                    "required": ["entities", "description", "details"],
                },
                tool_name="prescan", tool_description="Pre-scan image",
            )
            lines = [f"IMAGE: {img_file.name}", f"DESCRIPTION: {prescan.get('description', '')}", "", "ENTITIES:"]
            for e in prescan.get("entities", []):
                lines.append(f"  - {e['name']} ({e['type']})")
            lines.extend(["", "DETAILS:", prescan.get("details", "")])
            (prescan_dir / f"{img_file.stem}.txt").write_text("\n".join(lines))
            print(f"  {img_file.name}: {len(prescan.get('entities', []))} entities", flush=True)
        except Exception as e:
            print(f"  {img_file.name}: FAILED — {e}", flush=True)

    # query_image tool
    async def query_image(image_path: str, question: str) -> str:
        img_path = Path(image_path)
        if not img_path.exists():
            img_path = sample_dir / image_path
        if not img_path.exists():
            return f"Image not found: {image_path}"
        try:
            b64 = base64.b64encode(img_path.read_bytes()).decode()
            media_type = "image/jpeg"
            result = await relay.complete(
                model=settings.extraction_model, max_tokens=1024,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": question},
                ]}],
            )
            return result.text
        except Exception as e:
            return f"Error: {e}"

    image_tools = {
        "query_image": {
            "function": query_image,
            "schema": {
                "type": "function",
                "function": {
                    "name": "query_image",
                    "description": "Ask Haiku to look at an image and answer a question.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "image_path": {"type": "string"},
                            "question": {"type": "string"},
                        },
                        "required": ["image_path", "question"],
                    },
                },
            },
        },
    }

    # Seed
    seed_path = specs_dir / "image_seed.md"
    seed_path.write_text(SEED_IMAGE_GOLDEN_SET)

    # Evaluator
    evaluator_script = Path(__file__).resolve().parent / "src" / "jobs" / "evaluate_image_spec.py"

    print(f"Starting Phase 1 refine...", flush=True)
    print("=" * 60, flush=True)

    golden_result = await refine(
        artifact=str(seed_path),
        criteria={
            "coverage": "Reference list captures every identifiable entity visible in sample images",
            "description_quality": "Descriptions are accurate, specific, and searchable",
            "precision": "Every entity is grounded in what's actually visible",
        },
        primary="coverage",
        iterations=args.iterations,
        judge_mode="board",
        judge_panel=[
            {
                "name": "Coverage & Description",
                "lens": (
                    "Use three sources: pre-scans (image_prescans/*.txt), evaluator (eval-*/*.json), "
                    "and query_image tool for specific questions. Cross-reference golden set against all."
                ),
            },
            {
                "name": "Precision & Accuracy",
                "lens": (
                    "Use pre-scans, evaluator outputs, and query_image to verify entities. "
                    "Flag anything the golden set claims but Haiku can't confirm."
                ),
            },
        ],
        output_dir=specs_dir / "image_golden_test",
        generator_model=settings.classification_model,
        judge_model=settings.classification_model,
        clerk_model=settings.classification_model,
        evaluator=(
            f"uv run python {shlex.quote(str(evaluator_script))}"
            f" --candidate {{candidate_path}}"
            f" --samples-dir {shlex.quote(str(sample_dir))}"
            f" --golden-set {{candidate_path}}"
            f" --output-dir {{output_dir}}"
            f" --iteration {{iteration}}"
        ),
        background=(
            f"Pre-scans are in {prescan_dir}/ as .txt files.\n"
            f"Use query_image tool to ask Haiku about specific images.\n"
            f"DO NOT open .jpg files directly.\n\n"
            f"The golden set must contain per-image entities, descriptions, and tags."
        ),
        on_iteration=_make_iteration_recorder(job_id, "golden_set", args.db_path, str(specs_dir / "image_golden_test")),
        custom_tools=image_tools,
        **provider_kwargs,
    )

    print("=" * 60, flush=True)
    print(f"Phase 1 complete — best score: {golden_result.composite}/10", flush=True)

    # Save golden set
    golden_path = specs_dir / "image_golden_set_test.md"
    golden_path.write_text(golden_result.best_candidate)
    print(f"Golden set saved to {golden_path}", flush=True)

    conn = get_connection(args.db_path)
    conn.execute("UPDATE jobs SET status = 'completed' WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples-dir", required=True)
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument("--db-path", required=True)
    asyncio.run(run_phase1(parser.parse_args()))


if __name__ == "__main__":
    main()
