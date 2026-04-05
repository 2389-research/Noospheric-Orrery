# ABOUTME: Domain-specific spec simmering job — refines extraction spec for a single domain.
# ABOUTME: Starts from the general spec and adds domain-specific entity types via simmer-sdk.

import uuid
import json
from pathlib import Path
from simmer_sdk import refine
from ..db import get_connection
from ..config import get_settings
from .simmer_general import _make_iteration_recorder


async def run_simmer_domain(job: dict, db_path: str) -> None:
    """Domain-specific spec simmering.

    Same two-phase pattern as general simmering, but:
    - Samples docs from this domain only
    - Starts from the general spec's entity types (extends, not replaces)
    - Stores spec with domain_path set
    - Re-extracts domain docs with the new spec (additive)
    """
    settings = get_settings()
    config = json.loads(job["config"]) if job["config"] else {}
    domain_path = config.get("domain") or job["target"]

    conn = get_connection(db_path)

    # Get docs in this domain
    docs = conn.execute(
        """SELECT d.id, d.title, d.content FROM documents d
           JOIN document_domains dd ON d.id = dd.document_id
           WHERE dd.domain_path = ? AND d.status IN ('classified', 'extracted', 'enriched')
           ORDER BY RANDOM() LIMIT 10""",
        (domain_path,),
    ).fetchall()

    if not docs:
        conn.close()
        raise ValueError(f"No documents in domain {domain_path}")

    # Get the general spec to use as starting point
    general_spec = conn.execute(
        "SELECT spec_content FROM specs WHERE domain_path IS NULL ORDER BY version DESC LIMIT 1"
    ).fetchone()

    if general_spec:
        seed_content = f"""# Golden Set — Domain: {domain_path}

## Entity Type Taxonomy
Starting from the general extraction spec, extend with domain-specific types:

{general_spec[0]}

Add entity types specific to {domain_path} that the general spec misses.
Keep the general types but add domain-specific ones.

## Reference Entities

Read every sample document and list ALL entities you find. Each entity must actually
appear in at least one sample document — do not invent entities.

Format as a JSON array:
```json
[
  {{"name": "entity name lowercase", "type": "EntityType"}},
  ...
]
```

The reference entity list is the ground truth that extraction specs will be tested against.
Be thorough — every named person, organization, product, concept, place, and event
mentioned in the sample documents should appear here."""
    else:
        seed_content = f"""# Golden Set — Domain: {domain_path}

## Entity Type Taxonomy
- Discover what entity types matter for this specific domain
- Be more specific than generic types like Person, Organization, Thing

## Reference Entities

Read every sample document and list ALL entities you find as a JSON array:
```json
[
  {{"name": "entity name lowercase", "type": "EntityType"}},
  ...
]
```"""

    # Write samples and seed
    specs_dir = Path(settings.specs_dir)
    domain_dir = specs_dir / f"domain_{domain_path.replace('/', '_')}"
    domain_dir.mkdir(parents=True, exist_ok=True)
    sample_dir = domain_dir / "samples"
    sample_dir.mkdir(exist_ok=True)

    for doc in docs:
        (sample_dir / f"{doc[0]}.txt").write_text(doc[2])

    seed_path = domain_dir / "seed.md"
    seed_path.write_text(seed_content)
    conn.close()

    # Bedrock config
    bedrock_kwargs = {
        "api_provider": "bedrock",
        "aws_access_key": settings.aws_access_key,
        "aws_secret_key": settings.aws_secret_key,
        "aws_region": settings.aws_region,
    }

    job_id = job["id"]
    print(f"Simmering domain spec for: {domain_path} ({len(docs)} docs, job {job_id})", flush=True)

    # Phase 1: Golden set simmering (domain-specific) — type taxonomy + reference entities
    golden_result = await refine(
        artifact=str(seed_path),
        criteria={
            "coverage": f"The reference entity list contains every named entity found in the {domain_path} sample documents — no entity left behind",
            "precision": "Every entity in the reference list actually appears in at least one sample document — no hallucinated entities",
            "domain_specificity": f"Entity types include categories specific to {domain_path} that the general spec misses — not just generic Person/Organization",
        },
        primary="coverage",
        iterations=settings.simmer_iterations,
        judge_mode="board",
        judge_panel=[
            {
                "name": "Coverage & Depth",
                "lens": (
                    "Read every sample document carefully. Cross-reference the reference entity JSON list against the documents. "
                    f"Are there {domain_path}-specific entities mentioned in the docs that are missing from the list? "
                    "The list must be exhaustive."
                ),
            },
            {
                "name": "Precision & Quality",
                "lens": (
                    "For each entity in the reference JSON list, verify it actually appears in at least one sample document. "
                    "Check that entity types are correct and domain-specific where appropriate. "
                    "Flag any hallucinated entities not grounded in the source text."
                ),
            },
        ],
        output_dir=domain_dir / "golden",
        generator_model="claude-sonnet-4-6",
        judge_model="claude-sonnet-4-6",
        background=(
            f"Sample documents from domain '{domain_path}' are in {sample_dir}. Read ALL of them.\n\n"
            f"The golden set must contain TWO things:\n"
            f"1. An entity type taxonomy (including {domain_path}-specific types)\n"
            f"2. A JSON array of EVERY entity found in the sample documents\n\n"
            f"The reference entity list is the ground truth — extraction specs will be empirically "
            f"tested against it. Be thorough."
        ),
        on_iteration=_make_iteration_recorder(job_id, "golden_set", db_path, str(domain_dir / "golden")),
        **bedrock_kwargs,
    )

    # Phase 2: Extraction spec simmering (with empirical evaluator)
    golden_set_path = domain_dir / "golden_set.md"
    golden_set_path.write_text(golden_result.best_candidate)
    evaluator_script = Path(__file__).resolve().parent / "evaluate_spec.py"

    spec_result = await refine(
        artifact=golden_result.best_candidate,
        criteria={
            "coverage": "Finds all domain-specific entities from the golden set",
            "precision": "Zero false positives",
            "format_compliance": "Valid JSON with name and type fields",
        },
        primary="coverage",
        iterations=settings.simmer_iterations,
        judge_mode="board",
        judge_panel=[
            {
                "name": "Coverage & Depth",
                "lens": (
                    "BEFORE scoring, you MUST open and read the raw extraction JSON files in the eval-* directories. "
                    "The quantitative summary is approximate — your score must be based on what you see in the actual outputs. "
                    f"For each sample doc, read the .json file and check: did Haiku find the {domain_path}-specific entities that matter? "
                    "Are near-misses actually correct extractions with different phrasing? "
                    "Are apparent misses due to spec wording, or are those entities genuinely absent from that document?"
                ),
            },
            {
                "name": "Precision & Quality",
                "lens": (
                    "BEFORE scoring, you MUST open and read the raw extraction JSON files in the eval-* directories. "
                    "The quantitative summary is approximate — your score must be based on what you see in the actual outputs. "
                    "For each sample doc, check: are extracted entities grounded in the source text? "
                    "Are false positives truly wrong, or reasonable entities the golden set didn't include? "
                    "Is the spec causing Haiku to over-extract or hallucinate?"
                ),
            },
        ],
        output_dir=domain_dir / "spec",
        generator_model="claude-sonnet-4-6",
        judge_model="claude-sonnet-4-6",
        clerk_model="claude-haiku-4-5",
        evaluator=(
            f"python {evaluator_script}"
            f" --candidate {{candidate_path}}"
            f" --samples-dir {sample_dir}"
            f" --golden-set {golden_set_path}"
            f" --output-dir {{output_dir}}"
            f" --iteration {{iteration}}"
        ),
        background=(
            f"This spec will be executed by Haiku on documents in domain '{domain_path}'.\n"
            f"Golden set: {golden_result.best_candidate[:2000]}\n\n"
            f"IMPORTANT: Each iteration, the evaluator runs the candidate spec against sample docs using Haiku.\n"
            f"Raw extraction results are written to eval-N/ directories in the output directory.\n"
            f"READ the raw extraction JSON files — don't just trust the quantitative summary.\n"
            f"Look for near-misses, type mismatches, and systematic patterns the metrics miss."
        ),
        on_iteration=_make_iteration_recorder(job_id, "extraction_spec", db_path, str(domain_dir / "spec")),
        **bedrock_kwargs,
    )

    # Store spec
    conn = get_connection(db_path)

    # Get next version for this domain
    existing_version = conn.execute(
        "SELECT MAX(version) FROM specs WHERE domain_path = ?", (domain_path,)
    ).fetchone()[0]
    version = (existing_version or 0) + 1

    spec_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO specs (id, domain_path, version, spec_content, golden_set, score) VALUES (?, ?, ?, ?, ?, ?)",
        (spec_id, domain_path, version, spec_result.best_candidate, golden_result.best_candidate, spec_result.composite),
    )

    # Update domain spec_version
    conn.execute(
        "UPDATE domains SET spec_version = ? WHERE path = ?",
        (version, domain_path),
    )

    # Queue domain-specific batch extraction (additive)
    job_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO jobs (id, type, target, status, config) VALUES (?, 'extract_batch', ?, 'queued', ?)",
        (job_id, domain_path, json.dumps({"spec_id": spec_id, "scope": "domain", "domain": domain_path})),
    )

    conn.commit()
    conn.close()
    print(f"Domain spec for {domain_path}: v{version}, score {spec_result.composite}/10", flush=True)
