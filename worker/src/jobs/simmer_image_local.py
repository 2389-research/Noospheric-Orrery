# ABOUTME: Local image spec simmering — deterministic flow for Ollama (no tool calls).
# ABOUTME: Mirrors simmer-sdk prompt structure but with vision calls at known steps.

"""
Local image spec simmer — deterministic pipeline for Ollama.

Follows the same prompt structure as simmer-sdk's text pipeline:
- Generator: CRITERIA → CURRENT CANDIDATE → ASI → produce improved spec
- Evaluator: run spec against each image (vision call)
- Judge: per-image investigation → evidence → scoring → ASI
- Scorer: aggregate reviews → scores + composite + ASI

Single phase (not 2-phase like text) — refines the image extraction
spec directly. The general image spec is the seed, domain-specific
improvements are the goal.
"""

import base64
import json
import re
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
        Path("/app/orchestrator/specs/general_image.md"),
    ]
    for p in candidates:
        if p.exists():
            return p.read_text()
    return (
        "## Entity Types\n\n"
        "- Subject — the primary focus of the image\n"
        "- Object — identifiable items visible\n"
        "- Person — anyone visible or identifiable\n"
        "- Text — any readable text\n"
        "- Setting — the environment or location\n"
        "- Material — visible materials, textures, surfaces\n"
        "- Color — 2-4 most prominent colors\n\n"
        "## Rules\n\n"
        "- Extract ONLY what is actually visible\n"
        "- Be specific (not generic)\n"
        "- Names must be lowercase\n"
    )


def _image_to_b64(path: Path) -> tuple[str, str]:
    b64 = base64.b64encode(path.read_bytes()).decode()
    suffix = path.suffix.lower()
    media_type = {".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}.get(suffix, "image/jpeg")
    return b64, media_type


def _image_content_block(path: Path) -> dict:
    b64, media_type = _image_to_b64(path)
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}}


def _parse_json_from_text(text: str) -> dict | None:
    text = text.strip()
    if "```" in text:
        match = re.search(r'```(?:json)?\s*\n?(.*?)```', text, re.DOTALL)
        if match:
            text = match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None


# ---------------------------------------------------------------------------
# Step 1: Pre-scan (once, builds golden reference)
# ---------------------------------------------------------------------------

async def _prescan_image(relay: Relay, model: str, img_path: Path) -> dict:
    """Vision model looks at an image and produces a reference observation."""
    response = await relay.complete(
        model=model, max_tokens=2048,
        messages=[{"role": "user", "content": [
            _image_content_block(img_path),
            {"type": "text", "text": (
                "You are building a reference entity list for an image extraction spec.\n\n"
                "Look at this image carefully. List EVERY identifiable entity:\n\n"
                "For each entity, provide:\n"
                "  - name (lowercase, specific — 'cherry blossom tree' not 'tree')\n"
                "  - type (Subject, Object, Person, Text, Setting, Material, or Color)\n\n"
                "Then provide:\n"
                "  - A 2-3 sentence description (medium + subject, then details, then context)\n"
                "  - Notable visual details the spec should help extract\n\n"
                "Be exhaustive. This reference is the ground truth for scoring."
            )},
        ]}],
    )
    return {"image": img_path.name, "observations": response.text}


# ---------------------------------------------------------------------------
# Step 2: Evaluate (per iteration — runs spec against each image)
# ---------------------------------------------------------------------------

async def _evaluate_image(relay: Relay, model: str, img_path: Path, spec: str) -> dict:
    """Run candidate spec against an image, return extraction result as JSON."""
    response = await relay.complete(
        model=model, max_tokens=2048,
        messages=[{"role": "user", "content": [
            _image_content_block(img_path),
            {"type": "text", "text": (
                f"You are an extraction model. Follow this spec exactly:\n\n"
                f"EXTRACTION SPEC:\n{spec}\n\n"
                f"Extract entities from the image above following the spec.\n\n"
                f"Return a JSON object:\n"
                f'{{"entities": [{{"name": "...", "type": "..."}}, ...], '
                f'"description": "2-3 sentence description", '
                f'"tags": ["tag1", "tag2", ...]}}\n\n'
                f"Return ONLY the JSON object."
            )},
        ]}],
    )
    parsed = _parse_json_from_text(response.text)
    return parsed if parsed else {"entities": [], "description": response.text[:200], "tags": []}


# ---------------------------------------------------------------------------
# Step 3: Per-image review (judge investigates each image)
# ---------------------------------------------------------------------------

async def _review_image(relay: Relay, model: str, img_path: Path,
                        extraction: dict, prescan: dict) -> str:
    """Judge reviews extraction accuracy for a single image.

    Follows SDK judge pattern: investigation → evidence → assessment.
    """
    entities_text = "\n".join(
        f"  - {e['name']} ({e.get('type', '?')})" for e in extraction.get("entities", [])
    )
    response = await relay.complete(
        model=model, max_tokens=1024,
        messages=[{"role": "user", "content": [
            _image_content_block(img_path),
            {"type": "text", "text": (
                f"You are a judge reviewing an image extraction.\n\n"
                f"<investigation>\n"
                f"Look at the image. Compare what you see against the extraction below.\n"
                f"</investigation>\n\n"
                f"EXTRACTED ENTITIES:\n{entities_text}\n\n"
                f"EXTRACTED DESCRIPTION:\n{extraction.get('description', '(none)')}\n\n"
                f"REFERENCE OBSERVATIONS (from pre-scan):\n{prescan.get('observations', '(none)')}\n\n"
                f"<evidence>\n"
                f"List specific findings:\n"
                f"- Entities correctly extracted (hits)\n"
                f"- Entities visible but missing from extraction (misses)\n"
                f"- Entities extracted but NOT visible in image (false positives)\n"
                f"- Description accuracy issues\n"
                f"- Entity type errors\n"
                f"</evidence>\n\n"
                f"Provide your assessment in 3-5 sentences with specific entity names."
            )},
        ]}],
    )
    return response.text


# ---------------------------------------------------------------------------
# Step 4: Score iteration (aggregate reviews → scores + ASI)
# ---------------------------------------------------------------------------

async def _score_iteration(relay: Relay, model: str, reviews: list[dict],
                           criteria: dict, seed_scores: dict | None,
                           iteration: int) -> dict:
    """Aggregate per-image reviews into scores and ASI.

    Follows SDK scoring format: per-criterion score + evidence + ASI.
    """
    reviews_text = ""
    for r in reviews:
        reviews_text += f"\n--- {r['image']} ---\n{r['review']}\n"

    criteria_text = "\n".join(f"  - {k}: {v}" for k, v in criteria.items())
    seed_text = ""
    if seed_scores:
        seed_text = f"\nSEED SCORES (iteration 0 baseline):\n"
        for k, v in seed_scores.items():
            seed_text += f"  {k}: {v}/10\n"

    response = await relay.complete(
        model=model, max_tokens=2048,
        messages=[{"role": "user", "content": (
            f"You are scoring iteration {iteration} of an image extraction spec refinement.\n\n"
            f"CRITERIA:\n{criteria_text}\n"
            f"{seed_text}\n"
            f"PER-IMAGE EVIDENCE:\n{reviews_text}\n\n"
            f"<scoring>\n"
            f"ITERATION {iteration} SCORES:\n"
            f"Score each criterion 1-10 based on the evidence above.\n"
            f"For each: [criterion]: [N]/10 — [reasoning citing specific evidence]\n\n"
            f"COMPOSITE: average of all scores\n\n"
            f"ASI (highest-leverage direction):\n"
            f"The single most impactful change to the extraction spec that would "
            f"improve scores next iteration. Be specific — name entity types, "
            f"rules, or patterns to add/change.\n"
            f"</scoring>\n\n"
            f"Return JSON:\n"
            f'{{"scores": {{"criterion_name": score, ...}}, '
            f'"composite": average_score, '
            f'"asi": "specific improvement direction", '
            f'"key_change": "2-5 word summary"}}'
        )}],
    )
    parsed = _parse_json_from_text(response.text)
    if parsed and parsed.get("scores"):
        return parsed

    # Fallback: extract scores from text
    score_pattern = re.findall(r'(\w[\w_]*)\s*:\s*(\d+)/10', response.text)
    if score_pattern:
        scores = {k.lower(): int(v) for k, v in score_pattern}
        composite = round(sum(scores.values()) / len(scores), 1) if scores else 0
        # Try to extract ASI
        asi_match = re.search(r'ASI[^:]*:\s*(.+?)(?:\n\n|$)', response.text, re.DOTALL)
        asi = asi_match.group(1).strip()[:500] if asi_match else response.text[-300:]
        return {"scores": scores, "composite": composite, "asi": asi, "key_change": f"iteration-{iteration}"}

    return {"scores": {}, "composite": 0, "asi": response.text[:500], "key_change": "parse error"}


# ---------------------------------------------------------------------------
# Step 5: Generator (improve spec based on ASI)
# ---------------------------------------------------------------------------

async def _generate_improved_spec(relay: Relay, model: str, current_spec: str,
                                  asi: str, criteria: dict, iteration: int,
                                  background: str = "") -> str:
    """Generator produces improved spec based on ASI feedback.

    Follows SDK generator pattern: CRITERIA → CURRENT CANDIDATE → ASI → produce.
    """
    criteria_text = "\n".join(f"  - {k}: {v}" for k, v in criteria.items())
    response = await relay.complete(
        model=model, max_tokens=4096,
        messages=[{"role": "user", "content": (
            f"You are the generator in a simmer refinement loop (iteration {iteration}).\n\n"
            f"CRITERIA:\n{criteria_text}\n\n"
            f"{f'BACKGROUND:{chr(10)}{background}{chr(10)}{chr(10)}' if background else ''}"
            f"CURRENT CANDIDATE:\n{current_spec}\n\n"
            f"JUDGE FEEDBACK (ASI from previous round):\n{asi}\n\n"
            f"Write your improved candidate. Keep the same structure "
            f"(entity types, rules, output format). Apply the ASI feedback "
            f"to make the spec more accurate and domain-specific.\n\n"
            f"Report: what specifically changed and why (2-3 sentences at the top, "
            f"then the full improved spec)."
        )}],
    )
    return response.text


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def run_simmer_image_local(job: dict, db_path: str) -> None:
    """Deterministic image spec simmer for local/Ollama pipeline."""
    settings = get_settings()
    config = json.loads(job["config"]) if job.get("config") else {}
    iterations = config.get("iterations", settings.simmer_iterations)
    conn = get_connection(db_path)

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
        "extraction_quality": "Entities extracted match what's actually visible — high precision and coverage",
        "description_quality": "Descriptions are accurate, specific, and searchable",
        "domain_specificity": "The spec includes domain-specific entity types and recognition rules that improve extraction beyond the generic spec",
    }

    # Step 1: Pre-scan all images (golden reference)
    print(f"  Pre-scanning {len(sample_images)} images...", flush=True)
    prescans = {}
    for img in sample_images:
        try:
            prescans[img.name] = await _prescan_image(relay, judge_model, img)
            print(f"    {img.name}: done", flush=True)
        except Exception as e:
            print(f"    {img.name}: failed ({e})", flush=True)
            prescans[img.name] = {"image": img.name, "observations": f"Pre-scan failed: {e}"}

    current_spec = _load_general_image_spec()
    best_spec = current_spec
    best_composite = 0.0
    seed_scores = None

    background = (
        f"This is an image extraction spec for a visual knowledge graph.\n"
        f"The spec is used by a vision model to extract entities from images.\n"
        f"Sample images are {', '.join(img.name for img in sample_images)}.\n"
        f"Pre-scan observations describe what's visible in each image."
    )

    from .simmer_general import _make_iteration_recorder
    record_iteration = _make_iteration_recorder(job_id, "image_spec", db_path, str(specs_dir / "image_local"))

    for iteration in range(iterations + 1):
        print(f"  [image_spec] iteration {iteration}...", flush=True)

        # Step 2: Evaluate — run spec against each image
        extractions = {}
        for img in sample_images:
            try:
                extractions[img.name] = await _evaluate_image(relay, eval_model, img, current_spec)
            except Exception as e:
                print(f"    eval {img.name}: failed ({e})", flush=True)
                extractions[img.name] = {"entities": [], "description": "", "tags": []}

        # Step 3: Per-image review — judge investigates each
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

        # Step 4: Score
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

        if composite > best_composite:
            best_composite = composite
            best_spec = current_spec

        # Record iteration
        from simmer_sdk.types import IterationRecord
        record = IterationRecord(
            iteration=iteration,
            scores=scores,
            key_change=key_change,
            asi=asi,
            judge_mode="local",
            regressed=composite < best_composite and iteration > 0,
        )
        record.composite = round(composite, 1) if isinstance(composite, float) else composite
        await record_iteration(record, [], "")

        print(f"  [image_spec] iteration {iteration}: {composite}/10 — {key_change}", flush=True)

        # Step 5: Generate improved spec (skip on last iteration)
        if iteration < iterations and asi:
            current_spec = await _generate_improved_spec(
                relay, judge_model, best_spec, asi, criteria, iteration + 1, background,
            )

    # Store best spec
    conn = get_connection(db_path)
    spec_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO specs (id, domain_path, version, spec_content, golden_set, score, media_type) VALUES (?, NULL, 1, ?, ?, ?, 'image')",
        (spec_id, best_spec, "", best_composite),
    )

    batch_job_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO jobs (id, type, target, status, config) VALUES (?, 'extract_batch_image', 'general', 'queued', ?)",
        (batch_job_id, json.dumps({"spec_id": spec_id, "scope": "all_images"})),
    )
    conn.commit()
    conn.close()

    print(f"Image spec simmer complete: best {best_composite}/10, spec stored as {spec_id}", flush=True)
