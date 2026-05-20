# ABOUTME: Per-domain image spec simmering. Single-stage: static general image spec seed → add domain recognition context.
# ABOUTME: Image entity types (Subject/Object/Person/Text/Setting/Material/Color) are universal; only recognition vocabulary needs simmering.

import base64
import json
import shlex
import shutil
import uuid
from pathlib import Path
from orrery_relay import Relay
from simmer_sdk import refine
from ..db import get_connection
from ..config import get_settings
from .simmer_general import _make_iteration_recorder


# Static general image spec — the structural taxonomy is universal.
# Per-domain simmering adds recognition context, it does not replace these rules.
SEED_IMAGE_SPEC = """# Image Extraction Spec

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

## Domain Recognition Context
(none yet — domain simmering adds recognition vocabulary, naming conventions, and domain-specific guidance here)

## Output Format

```json
{
  "entities": [{"name": "entity name lowercase", "type": "EntityType"}, ...],
  "description": "2-3 sentences: medium + subject, visual details, context",
  "tags": ["category", "mood", "use-case"]
}
```
"""


async def run_simmer_domain_image(job: dict, db_path: str) -> None:
    """Per-domain image spec simmering.

    Single-stage simmer (no golden-set phase — image entity types are stable):
    - Seed = static general image spec (entity types, rules, format)
    - Iterations add domain recognition context (vocabulary, naming, recognition cues)
    - Evaluator runs Haiku on sample images and compares to a Haiku pre-scan
    """
    settings = get_settings()
    config = json.loads(job["config"]) if job.get("config") else {}
    domain_path = config.get("domain") or job["target"]
    iterations = config.get("iterations", settings.simmer_iterations)

    conn = get_connection(db_path)

    # Sample images scoped to this domain
    docs = conn.execute(
        """SELECT d.id, d.title, d.source_path FROM documents d
           JOIN document_domains dd ON d.id = dd.document_id
           WHERE dd.domain_path = ? AND d.content_type = 'image'
             AND d.status IN ('classified', 'extracted', 'enriched')
           ORDER BY RANDOM() LIMIT 5""",
        (domain_path,),
    ).fetchall()

    if not docs:
        conn.close()
        raise ValueError(f"No image documents in domain {domain_path}")

    # Stage samples on disk
    specs_dir = Path(settings.specs_dir)
    domain_dir = specs_dir / f"domain_image_{domain_path.replace('/', '_')}"
    domain_dir.mkdir(parents=True, exist_ok=True)
    sample_dir = domain_dir / "samples"
    if sample_dir.exists():
        for old in sample_dir.glob("*"):
            old.unlink()
    sample_dir.mkdir(exist_ok=True)

    for doc in docs:
        src = Path(doc["source_path"])
        if src.exists():
            shutil.copy2(src, sample_dir / f"{doc['id']}{src.suffix}")

    conn.close()

    # Pre-scan with Haiku to build a golden set the evaluator can compare against
    prescan_dir = domain_dir / "prescans"
    if prescan_dir.exists():
        for old in prescan_dir.glob("*"):
            old.unlink()
    prescan_dir.mkdir(exist_ok=True)

    relay = Relay.from_settings(settings)
    print(f"  Pre-scanning {len(docs)} images for domain {domain_path}...", flush=True)
    for img_file in sorted(sample_dir.glob("*.jpg")) + sorted(sample_dir.glob("*.jpeg")) + sorted(sample_dir.glob("*.png")):
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

    # Build golden set JSON from pre-scans
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

    golden_path = domain_dir / "golden_from_prescans.md"
    golden_path.write_text("# Golden Set\n\n```json\n" + json.dumps(golden_entries, indent=2) + "\n```\n")

    # Seed file — static general image spec with empty domain-context section
    seed_path = domain_dir / "seed.md"
    seed_path.write_text(SEED_IMAGE_SPEC)

    # LLM provider config
    # simmer-sdk only accepts anthropic/bedrock/ollama — translate "gateway" (our CF proxy)
    # to "anthropic" (the SDK is already pointed at the gateway via ANTHROPIC_BASE_URL).
    backend = settings.anthropic_backend
    api_provider = "anthropic" if backend == "gateway" else backend
    provider_kwargs = {"api_provider": api_provider}
    if backend == "bedrock":
        provider_kwargs.update({
            "aws_access_key": settings.aws_access_key,
            "aws_secret_key": settings.aws_secret_key,
            "aws_region": settings.aws_region,
        })
    elif backend == "ollama":
        provider_kwargs["ollama_url"] = settings.ollama_url

    job_id = job["id"]
    print(f"Simmering image spec for domain: {domain_path} ({len(docs)} images, {iterations} iterations, job {job_id})", flush=True)

    evaluator_script = Path(__file__).resolve().parent / "evaluate_image_spec.py"

    spec_result = await refine(
        artifact=str(seed_path),
        criteria={
            "extraction_quality": f"When run on {domain_path} images, the spec produces accurate, specific entities — not generic labels",
            "description_quality": f"Descriptions are accurate and use {domain_path}-appropriate vocabulary",
            "domain_specificity": f"The added domain context helps Haiku recognize {domain_path}-specific things it would miss with the general spec alone",
        },
        primary="extraction_quality",
        iterations=iterations,
        judge_mode="board",
        judge_panel=[
            {
                "name": "Extraction & Description",
                "lens": (
                    "Read eval-*/*.json for extractions and compare to pre-scans in prescans/*.txt. "
                    f"Does the domain context help Haiku be more specific about {domain_path} subjects? "
                    "Are entities named with appropriate domain vocabulary?"
                ),
            },
            {
                "name": "Generalizability & Domain Fit",
                "lens": (
                    "Read the spec itself. Is the domain context accurate and useful, or just noise? "
                    "Does it describe WHAT to look for in this domain, or does it hardcode specific entity names? "
                    f"Would it work on new {domain_path} images, or would it cause hallucinations on images outside this domain?"
                ),
            },
        ],
        output_dir=domain_dir / "spec",
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
            f"Per-domain image spec simmer for '{domain_path}'.\n"
            f"The seed is the static general image extraction spec — its entity type taxonomy and rules are universal.\n"
            f"Your job: add domain-specific RECOGNITION context to the '## Domain Recognition Context' section.\n"
            f"This means vocabulary ({domain_path}-specific subject names), naming conventions, things to watch for.\n\n"
            f"Pre-scans (raw Haiku observations) are in {prescan_dir}/*.txt\n"
            f"Evaluator runs the spec on each image each iteration — results in eval-N/*.json\n\n"
            f"DO NOT change the general entity type taxonomy. DO add domain recognition cues that help Haiku be specific."
        ),
        on_iteration=_make_iteration_recorder(job_id, "domain_image_spec", db_path, str(domain_dir / "spec")),
        **provider_kwargs,
    )

    # Store the simmered spec with media_type='image' and the domain_path
    conn = get_connection(db_path)
    existing_version = conn.execute(
        "SELECT MAX(version) FROM specs WHERE domain_path = ? AND media_type = 'image'",
        (domain_path,),
    ).fetchone()[0]
    version = (existing_version or 0) + 1

    spec_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO specs (id, domain_path, version, spec_content, golden_set, score, media_type) VALUES (?, ?, ?, ?, ?, ?, 'image')",
        (spec_id, domain_path, version, spec_result.best_candidate, golden_path.read_text(), spec_result.composite),
    )

    # Queue domain-scoped image batch extraction
    batch_job_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO jobs (id, type, target, status, config) VALUES (?, 'extract_batch_image', ?, 'queued', ?)",
        (batch_job_id, domain_path, json.dumps({"spec_id": spec_id, "scope": "domain", "domain": domain_path})),
    )

    conn.commit()
    conn.close()
    print(f"Domain image spec for {domain_path}: v{version}, score {spec_result.composite}/10", flush=True)
