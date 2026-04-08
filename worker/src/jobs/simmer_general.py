# ABOUTME: General spec simmering job — iteratively refines golden set and extraction spec.
# ABOUTME: Uses simmer-sdk for multi-phase refinement with board-mode judging.

import shlex
import uuid
import json
from pathlib import Path
from simmer_sdk import refine
from orrery_relay import Relay
from ..db import get_connection
from ..config import get_settings

SEED_GOLDEN_SET = """# Golden Set

## Entity Type Taxonomy
- Person — people, speakers, authors, creators
- Organization — companies, groups, teams, brands
- Topic — concepts, ideas, theories, fields, subjects
- Event — happenings, milestones, dates, releases
- Location — places, regions, settings, venues
- Thing — objects, tools, products, materials, artifacts

## Reference Entities

Read every sample document and list ALL entities you find. Each entity must actually
appear in at least one sample document — do not invent entities.

Format as a JSON array:
```json
[
  {"name": "entity name lowercase", "type": "EntityType"},
  ...
]
```

The reference entity list is the ground truth that extraction specs will be tested against.
Be thorough — every named person, organization, product, concept, place, and event
mentioned in the sample documents should appear here.
"""


SEED_IMAGE_GOLDEN_SET = """# Image Golden Set

## Visual Entity Types

- Subject — the primary focus of the image. For representations (paintings, miniatures, sculptures, screenshots), the subject is the representation itself. For multi-subject images, extract each distinct subject separately.
- Object — identifiable items visible (tools, products, vehicles, furniture, clothing, food, instruments, etc.)
- Person — anyone visible or identifiable
- Text — any readable text (signs, labels, watermarks, captions, handwriting, screens)
- Setting — the environment or location depicted or where the image was taken
- Material — visible materials, textures, or surfaces (metal, wood, fabric, glass, stone, water, paint, resin, etc.)
- Color — dominant or notable colors (use descriptive names: "cobalt blue", "burnished gold", not just "blue"). Extract 2-4 most prominent.

## Extraction Rules

- Extract ONLY what is actually visible — do not infer or hallucinate
- Distinguish what the image SHOWS (content) from what it IS (medium/context)
- Be specific ("cherry blossom tree" not "tree", "banksia flower" not "flower")
- For groups: extract the group AND notable individual items if distinguishable

## Reference Observations

Look at every sample image and for EACH image record:
1. ALL visual entities (name + type from taxonomy above)
2. A 2-3 sentence description: first sentence = medium + subject, second = visual details, third = context
3. Searchable tags (categories, mood, use-case — not just entity name repeats)
4. medium, shot_type, and representation

Format as a JSON array — one entry per image:
```json
[
  {
    "image": "filename",
    "entities": [{"name": "entity name lowercase", "type": "EntityType"}, ...],
    "description": "2-3 sentence description",
    "tags": ["category", "mood", "use-case"],
    "medium": "photograph | painting | illustration | diagram | screenshot | other",
    "shot_type": "product shot | close-up | wide angle | macro | portrait | candid | aerial | other",
    "representation": "direct | painted miniature | oil painting | scale model | other"
  },
  ...
]
```

The reference list is the ground truth for image extraction. Be thorough — every identifiable
subject, object, person, text, and setting should appear. Descriptions must be accurate enough
that someone searching for the image content would find it from the description alone.
"""


async def _parse_judgment_file(judgment_text: str, seed_scores: dict[str, int], settings) -> list[dict]:
    """Use Haiku to extract per-criterion details from a judgment file."""
    relay = Relay.from_settings(settings)

    prompt = f"""Extract per-criterion details from this judge output as JSON.

IMPORTANT: Use the scores from the "BOARD CONSENSUS SCORES" section at the very top of the output.
Do NOT use scores from the deliberation or synthesis sections below — those are individual judge scores.

Seed scores for reference: {json.dumps(seed_scores)}

Judge output:
{judgment_text[:4000]}

Return a JSON array only:
[
  {{
    "criterion": "criterion_name",
    "score": 8,
    "seed_score": 6,
    "evidence": "what the judge observed (1-2 sentences)",
    "improve": "what would make it better (1-2 sentences)"
  }}
]

If you can't parse a criterion, skip it. Return [] if unparseable."""

    try:
        response = await relay.complete(
            model=settings.classification_model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.text
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(text)
    except Exception as e:
        print(f"  Judgment parse failed: {e}", flush=True)
        return []


def _make_iteration_recorder(job_id: str, phase: str, db_path: str, output_dir: str):
    """Create an on_iteration callback that stores iteration data + criterion details."""
    seed_scores: dict[str, int] = {}

    async def on_iteration(record, trajectory, trajectory_table):
        nonlocal seed_scores

        # Track seed scores from iteration 0
        if record.iteration == 0 or not seed_scores:
            seed_scores = dict(record.scores)

        iteration_id = str(uuid.uuid4())
        conn = get_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO simmer_iterations (id, job_id, phase, iteration, scores, composite, key_change, asi, judge_mode, regressed, candidate_preview) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    iteration_id, job_id, phase, record.iteration,
                    json.dumps(record.scores), record.composite,
                    record.key_change, record.asi, record.judge_mode,
                    record.regressed, None,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        # Try to read and parse judgment file
        judgment_path = Path(output_dir) / f"iteration-{record.iteration}-judgment.md"
        if judgment_path.exists() and record.iteration > 0:
            judgment_text = judgment_path.read_text()
            settings = get_settings()
            details = await _parse_judgment_file(judgment_text, seed_scores, settings)

            if details:
                conn = get_connection(db_path)
                try:
                    for d in details:
                        conn.execute(
                            "INSERT INTO simmer_criterion_details (id, iteration_id, criterion, score, seed_score, evidence, improve) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (str(uuid.uuid4()), iteration_id, d.get("criterion", ""),
                             d.get("score", 0), d.get("seed_score", 0),
                             d.get("evidence", ""), d.get("improve", "")),
                        )
                    conn.commit()
                    print(f"  [{phase}] iter {record.iteration}: parsed {len(details)} criterion details", flush=True)
                finally:
                    conn.close()

        print(f"  [{phase}] iteration {record.iteration}: {record.composite}/10 — {record.key_change}", flush=True)
    return on_iteration


async def run_simmer_general(job: dict, db_path: str) -> None:
    settings = get_settings()
    config = json.loads(job["config"]) if job.get("config") else {}
    iterations = config.get("iterations", settings.simmer_iterations)
    conn = get_connection(db_path)

    docs = conn.execute(
        "SELECT id, title, content FROM documents WHERE status IN ('classified', 'extracted') ORDER BY RANDOM() LIMIT 10"
    ).fetchall()

    if not docs:
        conn.close()
        raise ValueError("No documents available to simmer general spec")

    specs_dir = Path(settings.specs_dir)
    specs_dir.mkdir(parents=True, exist_ok=True)
    sample_dir = specs_dir / "general_samples"
    # Clear old samples so only this run's docs are used
    if sample_dir.exists():
        for old_file in sample_dir.glob("*.txt"):
            old_file.unlink()
    sample_dir.mkdir(exist_ok=True)

    for doc in docs:
        (sample_dir / f"{doc[0]}.txt").write_text(doc[2])

    seed_path = specs_dir / "general_seed.md"
    seed_path.write_text(SEED_GOLDEN_SET)
    conn.close()

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

    job_id = job["id"]
    print(f"Simmering general spec (job {job_id})", flush=True)

    # Phase 1: Golden set simmering — produces type taxonomy + reference entity list
    golden_result = await refine(
        artifact=str(seed_path),
        criteria={
            "coverage": "The reference entity list contains every named entity found in the sample documents — no entity left behind",
            "precision": "Every entity in the reference list actually appears in at least one sample document — no hallucinated entities",
            "taxonomy_quality": "Entity types are meaningful, consistent, and correctly assigned — each entity has the right type",
        },
        primary="coverage",
        iterations=iterations,
        judge_mode="board",
        judge_panel=[
            {
                "name": "Coverage & Depth",
                "lens": (
                    "Read every sample document carefully. Cross-reference the reference entity JSON list against the documents. "
                    "Are there people, organizations, products, places, or events mentioned in the docs that are missing from the list? "
                    "The list must be exhaustive — every named entity in the corpus should appear."
                ),
            },
            {
                "name": "Precision & Quality",
                "lens": (
                    "For each entity in the reference JSON list, verify it actually appears in at least one sample document. "
                    "Check that entity types are correct — is a product labeled as an organization? Is a technology labeled as a thing? "
                    "Flag any hallucinated entities not grounded in the source text."
                ),
            },
        ],
        output_dir=specs_dir / "general_golden",
        generator_model=settings.classification_model,
        judge_model=settings.classification_model,
        clerk_model=settings.classification_model,
        background=(
            f"Sample documents are in {sample_dir}. Read ALL of them.\n\n"
            f"The golden set must contain TWO things:\n"
            f"1. An entity type taxonomy (the categories)\n"
            f"2. A JSON array of EVERY entity found in the sample documents\n\n"
            f"The reference entity list is the ground truth — extraction specs will be empirically "
            f"tested against it. If an entity is missing from this list, we can't measure whether "
            f"the extraction spec finds it. Be thorough."
        ),
        on_iteration=_make_iteration_recorder(job_id, "golden_set", db_path, str(specs_dir / "general_golden")),
        **provider_kwargs,
    )

    # Phase 2: Extraction spec simmering (with empirical evaluator)
    golden_set_path = specs_dir / "general_golden_set.md"
    golden_set_path.write_text(golden_result.best_candidate)
    evaluator_script = Path(__file__).resolve().parent / "evaluate_spec.py"

    spec_result = await refine(
        artifact=golden_result.best_candidate,
        criteria={
            "coverage": "When run on sample docs, the spec finds all entities from the golden set",
            "precision": "Zero false positives",
            "generalizability": "The spec uses general rules and entity type definitions, not hardcoded entity names — it would work on documents it has never seen",
            "format_compliance": "Output is valid JSON with name and type fields",
        },
        primary="coverage",
        iterations=iterations,
        judge_mode="board",
        judge_panel=[
            {
                "name": "Coverage & Depth",
                "lens": (
                    "BEFORE scoring, you MUST open and read the raw extraction JSON files in the eval-* directories. "
                    "The quantitative summary is approximate — your score must be based on what you see in the actual outputs. "
                    "For each sample doc, read the .json file and check: did Haiku find the entities that matter? "
                    "Are near-misses actually correct extractions with different phrasing? "
                    "Are apparent misses due to spec wording, or are those entities genuinely absent from that document?"
                ),
            },
            {
                "name": "Precision & Generalizability",
                "lens": (
                    "BEFORE scoring, you MUST open and read the raw extraction JSON files in the eval-* directories. "
                    "The quantitative summary is approximate — your score must be based on what you see in the actual outputs. "
                    "For each sample doc, check: are extracted entities grounded in the source text? "
                    "CRITICAL: Read the spec itself. Does it define entity types with general rules and examples, "
                    "or does it hardcode specific entity names from the sample docs? A good spec describes WHAT to look for "
                    "(e.g., 'Person — named individuals mentioned by name'), not WHO to look for (e.g., 'extract harper reed, shana fisher'). "
                    "Score generalizability low if the spec would fail on a new document about a different topic."
                ),
            },
        ],
        output_dir=specs_dir / "general_spec",
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
            f"This spec will be executed by Haiku to extract entities from documents.\n"
            f"Golden set: {golden_result.best_candidate[:2000]}\n\n"
            f"IMPORTANT: Each iteration, the evaluator runs the candidate spec against sample docs using Haiku.\n"
            f"Raw extraction results are written to eval-N/ directories in the output directory.\n"
            f"READ the raw extraction JSON files — don't just trust the quantitative summary.\n"
            f"Look for near-misses, type mismatches, and systematic patterns the metrics miss."
        ),
        on_iteration=_make_iteration_recorder(job_id, "extraction_spec", db_path, str(specs_dir / "general_spec")),
        **provider_kwargs,
    )

    # Store spec
    conn = get_connection(db_path)
    spec_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO specs (id, domain_path, version, spec_content, golden_set, score) VALUES (?, NULL, 1, ?, ?, ?)",
        (spec_id, spec_result.best_candidate, golden_result.best_candidate, spec_result.composite),
    )

    # Queue batch extraction
    batch_job_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO jobs (id, type, target, status, config) VALUES (?, 'extract_batch', 'general', 'queued', ?)",
        (batch_job_id, json.dumps({"spec_id": spec_id, "scope": "all_classified"})),
    )
    conn.commit()
    conn.close()


async def run_simmer_general_image(job: dict, db_path: str) -> None:
    """Simmer an image extraction spec — single-stage domain context approach.

    Unlike text (2-stage: golden set → extraction spec), images use one loop:
    - Seed = general image spec (entity types, format, rules)
    - Simmering adds domain-specific recognition context
    - Evaluator runs Haiku on sample images each iteration
    - Judges propose domain context additions via ASI

    The general spec handles structure. Domain context adds recognition
    (type vocabulary, naming conventions, domain knowledge).
    """
    settings = get_settings()
    config = json.loads(job["config"]) if job.get("config") else {}
    iterations = config.get("iterations", settings.simmer_iterations)
    conn = get_connection(db_path)

    # Get sample images
    docs = conn.execute(
        "SELECT id, title, image_path FROM documents WHERE content_type = 'image' AND status IN ('classified', 'extracted', 'enriched') ORDER BY RANDOM() LIMIT 5"
    ).fetchall()

    if not docs:
        conn.close()
        raise ValueError("No image documents available to simmer image spec")

    specs_dir = Path(settings.specs_dir)
    specs_dir.mkdir(parents=True, exist_ok=True)
    sample_dir = specs_dir / "image_samples"
    if sample_dir.exists():
        for old_file in sample_dir.glob("*"):
            old_file.unlink()
    sample_dir.mkdir(exist_ok=True)

    import shutil
    for doc in docs:
        src = Path(doc["image_path"])
        if src.exists():
            shutil.copy2(src, sample_dir / f"{doc['id']}{src.suffix}")

    conn.close()

    # Pre-scan with Haiku
    prescan_dir = specs_dir / "image_prescans"
    if prescan_dir.exists():
        for old_file in prescan_dir.glob("*"):
            old_file.unlink()
    prescan_dir.mkdir(exist_ok=True)

    relay = Relay.from_settings(settings)
    import base64
    print(f"  Pre-scanning {len(docs)} images with Haiku...", flush=True)
    for img_file in sorted(sample_dir.glob("*.jpg")) + sorted(sample_dir.glob("*.png")):
        try:
            b64 = base64.b64encode(img_file.read_bytes()).decode()
            media_type = "image/jpeg" if img_file.suffix.lower() in (".jpg", ".jpeg") else "image/png"
            prescan = await relay.complete_structured(
                model=settings.extraction_model, max_tokens=2048,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": "Describe everything visible. List entities, materials, colors, techniques, setting. Be exhaustive."},
                ]}],
                schema={"type": "object", "properties": {
                    "entities": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "type": {"type": "string"}}, "required": ["name", "type"]}},
                    "description": {"type": "string"},
                    "details": {"type": "string"},
                }, "required": ["entities", "description", "details"]},
                tool_name="prescan", tool_description="Pre-scan image",
            )
            lines = [f"IMAGE: {img_file.name}", f"DESCRIPTION: {prescan.get('description', '')}", "", "ENTITIES:"]
            for e in prescan.get("entities", []):
                if isinstance(e, dict) and "name" in e:
                    lines.append(f"  - {e['name']} ({e.get('type', 'Unknown')})")
            lines.extend(["", "DETAILS:", prescan.get("details", "")])
            (prescan_dir / f"{img_file.stem}.txt").write_text("\n".join(lines))
        except Exception as exc:
            print(f"  Warning: pre-scan failed for {img_file.name}: {exc}", flush=True)
    print(f"  Pre-scans written to {prescan_dir}", flush=True)

    # Build golden set from pre-scans for evaluator
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
        golden_entries.append({"image": txt_file.stem, "entities": entities, "description": desc, "tags": []})

    golden_path = specs_dir / "image_golden_from_prescans.md"
    golden_path.write_text("# Golden Set\n\n```json\n" + json.dumps(golden_entries, indent=2) + "\n```\n")

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

    job_id = job["id"]
    print(f"Simmering general IMAGE spec (job {job_id})", flush=True)

    # query_image tool
    async def query_image(image_path: str, question: str) -> str:
        img_path = Path(image_path)
        if not img_path.exists():
            img_path = sample_dir / image_path
        if not img_path.exists():
            return f"Image not found: {image_path}"
        try:
            b64 = base64.b64encode(img_path.read_bytes()).decode()
            media_type = "image/jpeg" if img_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
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

    # Write seed — general image spec with empty domain context
    seed_path = specs_dir / "image_seed.md"
    seed_path.write_text(SEED_IMAGE_GOLDEN_SET)

    evaluator_script = Path(__file__).resolve().parent / "evaluate_image_spec.py"

    # Single-stage simmer: general spec seed → add domain context
    spec_result = await refine(
        artifact=str(seed_path),
        criteria={
            "extraction_quality": "When run on sample images, the spec + domain context produces accurate, specific entities",
            "description_quality": "Descriptions are accurate, specific, and searchable — improved by domain knowledge",
            "domain_specificity": "The domain context helps Haiku recognize domain-specific things it would miss with the general spec alone",
        },
        primary="extraction_quality",
        iterations=iterations,
        judge_mode="board",
        judge_panel=[
            {
                "name": "Extraction & Description",
                "lens": (
                    "Read eval-*/*.json for Haiku extractions. Compare to pre-scans in image_prescans/*.txt. "
                    "Use query_image to verify specifics. Does the domain context help Haiku be more specific?"
                ),
            },
            {
                "name": "Generalizability & Domain Fit",
                "lens": (
                    "Read the spec itself. Is the domain context accurate and helpful? "
                    "Does it add real recognition value or just repeat the general spec? "
                    "Would it cause hallucinations on images outside this domain?"
                ),
            },
        ],
        output_dir=specs_dir / "image_spec",
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
            f"This is an image spec simmer. The seed is the general image extraction spec.\n"
            f"Your job: add domain-specific recognition context to help Haiku extract better.\n\n"
            f"Pre-scans (Haiku's raw observations) are in {prescan_dir}/*.txt\n"
            f"Evaluator runs Haiku with the spec each iteration — results in eval-N/*.json\n"
            f"Use query_image to investigate specific images.\n"
            f"DO NOT open .jpg files directly.\n\n"
            f"The general spec structure (entity types, rules, output format) should stay intact.\n"
            f"Add domain knowledge that helps Haiku recognize what it's looking at."
        ),
        on_iteration=_make_iteration_recorder(job_id, "domain_spec", db_path, str(specs_dir / "image_spec")),
        custom_tools=image_tools,
        **provider_kwargs,
    )

    # Store spec
    conn = get_connection(db_path)
    spec_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO specs (id, domain_path, version, spec_content, golden_set, score, media_type) VALUES (?, NULL, 1, ?, ?, ?, 'image')",
        (spec_id, spec_result.best_candidate, "", spec_result.composite),
    )

    # Queue batch extraction for images
    batch_job_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO jobs (id, type, target, status, config) VALUES (?, 'extract_batch_image', 'general', 'queued', ?)",
        (batch_job_id, json.dumps({"spec_id": spec_id, "scope": "all_images"})),
    )
    conn.commit()
    conn.close()
