# ABOUTME: Local image spec simmering — deterministic flow for Ollama (no tool calls).
# ABOUTME: Pre-scans images, runs evaluator per iteration, judges via vision review.

"""
Local image spec simmer — deterministic pipeline for Ollama.

Flow per iteration:
  1. Pre-scan: vision model looks at each image, generates reference observations
  2. Generator: improves the spec based on ASI feedback (text only, no vision)
  3. Evaluator: runs candidate spec against each image via vision model
  4. Per-image review: vision model compares extraction output to actual image
  5. Scoring: model reads all per-image reviews, scores criteria, writes ASI

No tool calls. Each step is a single relay.complete() with known inputs.
"""

import base64
import json
import shutil
import uuid
from pathlib import Path

from orrery_relay import Relay
from ..db import get_connection
from ..config import get_settings


def _load_general_image_spec() -> str:
    """Load the general image spec — check common locations."""
    candidates = [
        Path(__file__).resolve().parent.parent.parent.parent / "orchestrator" / "specs" / "general_image.md",
        Path("/app/orchestrator/specs/general_image.md"),  # Docker layout
    ]
    for p in candidates:
        if p.exists():
            return p.read_text()
    return (
        "Extract all visible entities (subjects, objects, people, text, settings, materials, colors). "
        "For each entity: lowercase name + type. Also produce a 2-3 sentence description and searchable tags."
    )


def _image_to_b64(path: Path) -> tuple[str, str]:
    """Read image file, return (base64_data, media_type)."""
    b64 = base64.b64encode(path.read_bytes()).decode()
    suffix = path.suffix.lower()
    media_type = {".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}.get(suffix, "image/jpeg")
    return b64, media_type


def _image_content_block(path: Path) -> dict:
    b64, media_type = _image_to_b64(path)
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}}


async def _prescan_image(relay: Relay, model: str, img_path: Path) -> dict:
    """Vision model looks at an image and describes what it sees."""
    response = await relay.complete(
        model=model, max_tokens=2048,
        messages=[{"role": "user", "content": [
            _image_content_block(img_path),
            {"type": "text", "text": (
                "Describe everything visible in this image. List:\n"
                "1. All identifiable entities (subjects, objects, people, text, settings, materials)\n"
                "2. A 2-3 sentence description\n"
                "3. Notable colors and visual details\n\n"
                "Be exhaustive and specific. Use lowercase names."
            )},
        ]}],
    )
    return {"image": img_path.name, "observations": response.text}


async def _evaluate_image(relay: Relay, model: str, img_path: Path, spec: str) -> dict:
    """Run candidate spec against an image, return extraction result."""
    response = await relay.complete(
        model=model, max_tokens=2048,
        messages=[{"role": "user", "content": [
            _image_content_block(img_path),
            {"type": "text", "text": (
                f"Using this extraction spec, extract entities from the image.\n\n"
                f"SPEC:\n{spec}\n\n"
                f"Return a JSON object with:\n"
                f'  "entities": [{{"name": "...", "type": "..."}}, ...]\n'
                f'  "description": "2-3 sentence description"\n'
                f'  "tags": ["tag1", "tag2", ...]\n\n'
                f"Return ONLY the JSON object."
            )},
        ]}],
    )
    # Parse JSON from response
    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"entities": [], "description": text[:200], "tags": []}


async def _review_image(relay: Relay, model: str, img_path: Path,
                        extraction: dict, prescan: dict) -> str:
    """Vision model reviews extraction accuracy against the actual image."""
    entities_text = "\n".join(
        f"  - {e['name']} ({e.get('type', '?')})" for e in extraction.get("entities", [])
    )
    response = await relay.complete(
        model=model, max_tokens=1024,
        messages=[{"role": "user", "content": [
            _image_content_block(img_path),
            {"type": "text", "text": (
                f"Review this extraction against what you see in the image.\n\n"
                f"EXTRACTED ENTITIES:\n{entities_text}\n\n"
                f"EXTRACTED DESCRIPTION:\n{extraction.get('description', '(none)')}\n\n"
                f"REFERENCE OBSERVATIONS:\n{prescan.get('observations', '(none)')}\n\n"
                f"Evaluate:\n"
                f"1. Are all extracted entities actually visible? (precision)\n"
                f"2. Are there visible things missing from the extraction? (coverage)\n"
                f"3. Is the description accurate and specific? (quality)\n"
                f"4. Are entity types correct?\n\n"
                f"Be specific about what's wrong or missing. 3-5 sentences."
            )},
        ]}],
    )
    return response.text


async def _score_iteration(relay: Relay, model: str, reviews: list[dict],
                           criteria: dict, seed_scores: dict | None,
                           iteration: int) -> dict:
    """Score the iteration based on collected per-image reviews."""
    reviews_text = ""
    for r in reviews:
        reviews_text += f"\n--- {r['image']} ---\n{r['review']}\n"

    criteria_text = "\n".join(f"  - {k}: {v}" for k, v in criteria.items())
    seed_text = ""
    if seed_scores:
        seed_text = f"\nSeed scores for reference: {json.dumps(seed_scores)}\n"

    response = await relay.complete(
        model=model, max_tokens=2048,
        messages=[{"role": "user", "content": (
            f"You are scoring iteration {iteration} of an image extraction spec refinement.\n\n"
            f"CRITERIA:\n{criteria_text}\n{seed_text}\n"
            f"PER-IMAGE REVIEWS:\n{reviews_text}\n\n"
            f"Based on these reviews, score each criterion 1-10.\n"
            f"Then write an ASI (Actionable Specific Improvement) — the single highest-leverage "
            f"change for the next iteration.\n\n"
            f"Return JSON:\n"
            f'{{"scores": {{"criterion_name": score, ...}}, '
            f'"composite": average_score, '
            f'"asi": "the one thing to change next", '
            f'"key_change": "2-5 word summary"}}'
        )}],
    )
    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"scores": {}, "composite": 0, "asi": text[:500], "key_change": "parse error"}


async def _generate_improved_spec(relay: Relay, model: str, current_spec: str,
                                  asi: str, criteria: dict, iteration: int) -> str:
    """Generator produces improved spec based on ASI feedback."""
    criteria_text = "\n".join(f"  - {k}: {v}" for k, v in criteria.items())
    response = await relay.complete(
        model=model, max_tokens=4096,
        messages=[{"role": "user", "content": (
            f"You are improving an image extraction spec (iteration {iteration}).\n\n"
            f"CURRENT SPEC:\n{current_spec}\n\n"
            f"JUDGE FEEDBACK (what to improve):\n{asi}\n\n"
            f"CRITERIA:\n{criteria_text}\n\n"
            f"Produce the improved spec. Keep the same structure (entity types, rules, output format). "
            f"Apply the feedback to make the spec more accurate and specific. "
            f"Return ONLY the spec text, no commentary."
        )}],
    )
    return response.text


async def run_simmer_image_local(job: dict, db_path: str) -> None:
    """Deterministic image spec simmer for local/Ollama pipeline.

    No tool calls, no agent loop. Each step gets exactly the inputs it needs.
    Vision calls happen in pre-scan, evaluator, and per-image review.
    """
    settings = get_settings()
    config = json.loads(job["config"]) if job.get("config") else {}
    iterations = config.get("iterations", settings.simmer_iterations)
    conn = get_connection(db_path)

    # Get sample images
    docs = conn.execute(
        "SELECT id, title, source_path FROM documents WHERE content_type = 'image' "
        "AND status IN ('classified', 'extracted', 'enriched') ORDER BY RANDOM() LIMIT 5"
    ).fetchall()

    if not docs:
        conn.close()
        raise ValueError("No image documents available for image spec simmering")

    specs_dir = Path(settings.specs_dir)
    specs_dir.mkdir(parents=True, exist_ok=True)
    sample_dir = specs_dir / "image_samples"
    if sample_dir.exists():
        for f in sample_dir.glob("*"):
            f.unlink()
    sample_dir.mkdir(exist_ok=True)

    # Copy sample images
    for doc in docs:
        src = Path(doc["source_path"])
        if src.exists():
            shutil.copy2(src, sample_dir / f"{doc['id']}{src.suffix}")

    conn.close()

    relay = Relay.from_settings(settings)
    judge_model = settings.classification_model
    eval_model = settings.extraction_model
    job_id = job["id"]

    sample_images = sorted(
        f for f in sample_dir.iterdir()
        if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    )

    if not sample_images:
        raise ValueError(f"No image files found in {sample_dir}")

    print(f"Simmering image spec locally ({len(sample_images)} images, {iterations} iterations, job {job_id})", flush=True)

    criteria = {
        "extraction_quality": "Entities extracted match what's actually visible in the image",
        "description_quality": "Descriptions are accurate, specific, and searchable",
        "domain_specificity": "The spec helps the model recognize domain-specific things it would otherwise miss",
    }

    # Step 1: Pre-scan all images (once)
    print(f"  Pre-scanning {len(sample_images)} images...", flush=True)
    prescans = {}
    for img in sample_images:
        try:
            prescans[img.name] = await _prescan_image(relay, judge_model, img)
            print(f"    {img.name}: done", flush=True)
        except Exception as e:
            print(f"    {img.name}: failed ({e})", flush=True)
            prescans[img.name] = {"image": img.name, "observations": f"Pre-scan failed: {e}"}

    # Seed spec
    current_spec = _load_general_image_spec() or "Extract all visible entities (subjects, objects, people, text, settings, materials, colors) with names and types."
    best_spec = current_spec
    best_composite = 0.0
    seed_scores = None

    from .simmer_general import _make_iteration_recorder
    record_iteration = _make_iteration_recorder(job_id, "image_spec", db_path, str(specs_dir / "image_local"))

    # Iteration loop: seed + N rounds
    for iteration in range(iterations + 1):
        print(f"  [image_spec] iteration {iteration}...", flush=True)

        # Evaluate: run spec against each image
        extractions = {}
        for img in sample_images:
            try:
                extractions[img.name] = await _evaluate_image(relay, eval_model, img, current_spec)
            except Exception as e:
                print(f"    eval {img.name}: failed ({e})", flush=True)
                extractions[img.name] = {"entities": [], "description": "", "tags": []}

        # Per-image review: vision model compares extraction to image
        reviews = []
        for img in sample_images:
            try:
                review_text = await _review_image(
                    relay, judge_model, img,
                    extractions.get(img.name, {}),
                    prescans.get(img.name, {}),
                )
                reviews.append({"image": img.name, "review": review_text})
            except Exception as e:
                reviews.append({"image": img.name, "review": f"Review failed: {e}"})

        # Score
        scoring = await _score_iteration(
            relay, judge_model, reviews, criteria, seed_scores, iteration,
        )

        scores = scoring.get("scores", {})
        composite = scoring.get("composite", 0)
        asi = scoring.get("asi", "")
        key_change = scoring.get("key_change", f"iteration-{iteration}")

        if iteration == 0:
            seed_scores = scores
            key_change = "seed"

        # Track best
        if composite > best_composite:
            best_composite = composite
            best_spec = current_spec

        # Record iteration (reuse text simmer's recorder)
        from simmer_sdk.types import IterationRecord
        record = IterationRecord(
            iteration=iteration,
            scores=scores,
            composite=round(composite, 1) if isinstance(composite, float) else composite,
            key_change=key_change,
            asi=asi,
            judge_mode="local",
            regressed=composite < best_composite and iteration > 0,
            best_candidate=current_spec,
        )

        # Fake trajectory for the recorder
        await record_iteration(record, [], "")

        print(f"  [image_spec] iteration {iteration}: {composite}/10 — {key_change}", flush=True)

        # Generate improved spec for next iteration (skip on last)
        if iteration < iterations and asi:
            current_spec = await _generate_improved_spec(
                relay, judge_model, best_spec, asi, criteria, iteration + 1,
            )

    # Store best spec
    conn = get_connection(db_path)
    spec_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO specs (id, domain_path, version, spec_content, golden_set, score, media_type) VALUES (?, NULL, 1, ?, ?, ?, 'image')",
        (spec_id, best_spec, "", best_composite),
    )

    # Queue batch extraction
    batch_job_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO jobs (id, type, target, status, config) VALUES (?, 'extract_batch_image', 'general', 'queued', ?)",
        (batch_job_id, json.dumps({"spec_id": spec_id, "scope": "all_images"})),
    )

    conn.execute(
        "UPDATE jobs SET status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (job_id,),
    )
    conn.commit()
    conn.close()

    print(f"Image spec simmer complete: best {best_composite}/10, spec stored as {spec_id}", flush=True)
