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

    bedrock_kwargs = {
        "api_provider": "bedrock",
        "aws_access_key": settings.aws_access_key,
        "aws_secret_key": settings.aws_secret_key,
        "aws_region": settings.aws_region,
    }

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
        iterations=settings.simmer_iterations,
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
        generator_model="claude-sonnet-4-6",
        judge_model="claude-sonnet-4-6",
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
        **bedrock_kwargs,
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
        iterations=settings.simmer_iterations,
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
        generator_model="claude-sonnet-4-6",
        judge_model="claude-sonnet-4-6",
        clerk_model="claude-haiku-4-5",
        evaluator=(
            f"python {shlex.quote(str(evaluator_script))}"
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
        **bedrock_kwargs,
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
