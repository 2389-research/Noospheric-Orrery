#!/usr/bin/env python
"""Proof of concept: single-stage image domain simmer.

Seed = general image spec. One loop that adds domain-specific
recognition context to help Haiku extract better.

Usage:
  uv run python test_image_domain_simmer.py \
    --samples-dir /data/specs/image_samples \
    --iterations 2 \
    --db-path /data/workspaces/31e52a94/orrery.db
"""

import argparse
import asyncio
import base64
import shlex
import uuid
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# The general image spec — this is the seed
GENERAL_IMAGE_SPEC = """# Image Extraction Spec

For each image, extract structured information about what is visible.
Distinguish between what the image SHOWS (content) and what it IS (medium/context).

## Entity Types
- Subject — primary focus. For representations (miniatures, paintings, etc.), the subject is the representation itself.
- Object — identifiable items visible
- Person — anyone visible
- Text — readable text
- Setting — environment or location
- Material — visible materials, textures, surfaces
- Color — dominant colors (descriptive names: "cobalt blue" not "blue")

## Rules
- Extract ONLY what is visible — no hallucination
- Lowercase entity names
- Be specific ("cherry blossom tree" not "tree")
- For groups: extract group AND notable individuals

## Output
```json
{
  "entities": [{"name": "...", "type": "..."}],
  "description": "First sentence: medium + subject. Second: visual details. Third: context.",
  "tags": ["category", "mood", "use-case"],
  "medium": "photograph | painting | illustration | other",
  "shot_type": "product shot | close-up | wide angle | macro | other",
  "representation": "direct | painted miniature | oil painting | other"
}
```

## Domain Context
(none yet — domain simmering adds recognition context here)
"""


async def main(args):
    from simmer_sdk import refine
    from orrery_relay import Relay
    from src.config import get_settings
    from src.db import get_connection

    settings = get_settings()
    relay = Relay.from_settings(settings)

    sample_dir = Path(args.samples_dir)
    specs_dir = Path(settings.specs_dir)
    output_dir = specs_dir / "image_domain_test"
    output_dir.mkdir(parents=True, exist_ok=True)

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
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES (?, 'test_image_domain', 'general', 'running')", (job_id,))
    conn.commit()
    conn.close()

    # Pre-scan with Haiku
    prescan_dir = specs_dir / "image_prescans"
    prescan_dir.mkdir(parents=True, exist_ok=True)
    for old in prescan_dir.glob("*"):
        old.unlink()

    images = sorted(f for f in sample_dir.iterdir() if f.suffix.lower() in {".jpg", ".jpeg", ".png"})
    print(f"Domain simmer POC — {len(images)} images, {args.iterations} iterations", flush=True)
    print(f"Pre-scanning...", flush=True)

    for img_file in images:
        try:
            b64 = base64.b64encode(img_file.read_bytes()).decode()
            media_type = "image/jpeg" if img_file.suffix.lower() in (".jpg", ".jpeg") else "image/png"
            prescan = await relay.complete_structured(
                model=settings.extraction_model, max_tokens=2048,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": "Describe everything visible. List entities, materials, colors, techniques, setting. Be exhaustive."},
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
                if isinstance(e, dict) and "name" in e:
                    lines.append(f"  - {e['name']} ({e.get('type', 'Unknown')})")
            lines.extend(["", "DETAILS:", prescan.get("details", "")])
            (prescan_dir / f"{img_file.stem}.txt").write_text("\n".join(lines))
            print(f"  {img_file.name}: {len(prescan.get('entities', []))} entities", flush=True)
        except Exception as exc:
            print(f"  {img_file.name}: FAILED — {exc}", flush=True)

    # query_image tool
    async def query_image(image_path: str, question: str) -> str:
        img_path = Path(image_path)
        if not img_path.exists():
            img_path = sample_dir / image_path
        if not img_path.exists():
            return f"Not found: {image_path}"
        try:
            b64 = base64.b64encode(img_path.read_bytes()).decode()
            result = await relay.complete(
                model=settings.extraction_model, max_tokens=1024,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
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

    # Write seed
    seed_path = output_dir / "seed.md"
    seed_path.write_text(GENERAL_IMAGE_SPEC)

    # Evaluator — runs the spec against images, compares to pre-scans
    evaluator_script = Path(__file__).resolve().parent / "src" / "jobs" / "evaluate_image_spec.py"

    # Build a simple golden set from pre-scans for the evaluator to diff against
    golden_entries = []
    for txt_file in sorted(prescan_dir.glob("*.txt")):
        content = txt_file.read_text()
        entities = []
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("- ") and "(" in line:
                name = line[2:line.rfind("(")].strip()
                etype = line[line.rfind("(")+1:line.rfind(")")].strip()
                entities.append({"name": name.lower(), "type": etype.lower()})
        desc_match = content.split("DESCRIPTION: ", 1)
        desc = desc_match[1].split("\n")[0] if len(desc_match) > 1 else ""
        golden_entries.append({
            "image": txt_file.stem,
            "entities": entities,
            "description": desc,
            "tags": [],
        })

    import json
    golden_path = output_dir / "golden_from_prescans.md"
    golden_path.write_text("# Golden Set (from pre-scans)\n\n```json\n" + json.dumps(golden_entries, indent=2) + "\n```\n")

    print(f"\nGolden set: {sum(len(e['entities']) for e in golden_entries)} entities across {len(golden_entries)} images", flush=True)
    print("=" * 60, flush=True)

    from src.jobs.simmer_general import _make_iteration_recorder

    result = await refine(
        artifact=str(seed_path),
        criteria={
            "extraction_quality": "When run on sample images, the spec + domain context produces accurate, specific entities that match what's visible",
            "description_quality": "Descriptions are accurate, specific, and searchable — improved by domain knowledge",
            "domain_specificity": "The domain context helps Haiku recognize domain-specific things it would miss with the general spec alone",
        },
        primary="extraction_quality",
        iterations=args.iterations,
        judge_mode="board",
        judge_panel=[
            {
                "name": "Extraction & Description",
                "lens": (
                    "Read eval-*/*.json for what Haiku extracted with the current spec. "
                    "Compare to pre-scans in image_prescans/*.txt. "
                    "Use query_image to verify specifics. "
                    "Does the domain context help Haiku be more specific and accurate?"
                ),
            },
            {
                "name": "Generalizability & Domain Fit",
                "lens": (
                    "Read the spec itself. Is the domain context accurate and helpful? "
                    "Does it add real recognition value or just repeat what the general spec already does? "
                    "Would it cause hallucinations on images outside this domain?"
                ),
            },
        ],
        output_dir=output_dir,
        generator_model=settings.classification_model,
        judge_model=settings.classification_model,
        clerk_model=settings.classification_model,
        evaluator=(
            f"uv run python {shlex.quote(str(evaluator_script))}"
            f" --candidate {{candidate_path}}"
            f" --samples-dir {shlex.quote(str(sample_dir))}"
            f" --golden-set {shlex.quote(str(golden_path))}"
            f" --output-dir {{output_dir}}"
            f" --iteration {{iteration}}"
        ),
        background=(
            f"This is a DOMAIN image simmer. The seed is the general image extraction spec.\n"
            f"Your job: add domain-specific recognition context to the '## Domain Context' section.\n"
            f"This context helps Haiku recognize domain-specific things in images.\n\n"
            f"Pre-scans (Haiku's raw observations) are in {prescan_dir}/*.txt\n"
            f"Evaluator runs Haiku with the spec each iteration — results in eval-N/*.json\n"
            f"Use query_image to investigate specific images.\n"
            f"DO NOT open .jpg files directly.\n\n"
            f"The general spec structure (entity types, rules, output format) should NOT change.\n"
            f"Only the Domain Context section should be amended with domain knowledge."
        ),
        on_iteration=_make_iteration_recorder(job_id, "domain_spec", args.db_path, str(output_dir)),
        custom_tools=image_tools,
        **provider_kwargs,
    )

    print("=" * 60, flush=True)
    print(f"Done — best score: {result.composite}/10", flush=True)
    print(f"Best candidate: {len(result.best_candidate)} chars", flush=True)

    # Show the domain context that was added
    best = result.best_candidate
    if "## Domain Context" in best:
        domain_section = best.split("## Domain Context")[1]
        print(f"\n--- Domain Context Added ---")
        print(domain_section[:500])

    # Save
    result_path = output_dir / "result.md"
    Path(result_path).write_text(result.best_candidate)
    print(f"\nSaved to {result_path}", flush=True)

    conn = get_connection(args.db_path)
    conn.execute("UPDATE jobs SET status = 'completed' WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples-dir", required=True)
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument("--db-path", required=True)
    asyncio.run(main(parser.parse_args()))
