# ABOUTME: General spec simmering job — iteratively refines golden set and extraction spec.
# ABOUTME: Uses simmer-sdk for multi-phase refinement with board-mode judging.

import uuid
import json
from pathlib import Path
from simmer_sdk import refine
from orrery_relay import Relay
from ..db import get_connection
from ..config import get_settings

SEED_ONTOLOGY = """Entity types to extract:
- Person — people, speakers, authors, creators
- Organization — companies, groups, teams, brands
- Topic — concepts, ideas, theories, fields, subjects
- Event — happenings, milestones, dates, releases
- Location — places, regions, settings, venues
- Thing — objects, tools, products, materials, artifacts

For each entity found in the text, output:
{"name": "entity name", "type": "EntityType"}

Rules:
- Only extract entities explicitly mentioned in the text
- Normalize names to lowercase
- Do not hallucinate entities not present in the source
"""


async def _parse_judgment_file(judgment_text: str, seed_scores: dict[str, int], settings) -> list[dict]:
    """Use Haiku to extract per-criterion details from a judgment file."""
    relay = Relay.from_settings(settings)

    prompt = f"""Extract per-criterion details from this judge output as JSON.

Seed scores for reference: {json.dumps(seed_scores)}

Judge output:
{judgment_text[:3000]}

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
            model=settings.extraction_model,
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
    sample_dir.mkdir(exist_ok=True)

    for doc in docs:
        (sample_dir / f"{doc[0]}.txt").write_text(doc[2])

    seed_path = specs_dir / "general_seed.md"
    seed_path.write_text(SEED_ONTOLOGY)
    conn.close()

    bedrock_kwargs = {
        "api_provider": "bedrock",
        "aws_access_key": settings.aws_access_key,
        "aws_secret_key": settings.aws_secret_key,
        "aws_region": settings.aws_region,
    }

    job_id = job["id"]
    print(f"Simmering general spec (job {job_id})", flush=True)

    # Phase 1: Golden set simmering
    golden_result = await refine(
        artifact=str(seed_path),
        criteria={
            "coverage": "Captures all entity types present in sample documents",
            "precision": "No hallucinated entities, no noise",
            "taxonomy_quality": "Entity types are meaningful, consistent, and cover the domain",
        },
        primary="coverage",
        iterations=settings.simmer_iterations,
        judge_mode="board",
        judge_panel=[
            {"name": "Coverage & Depth", "lens": "Focus on whether the spec captures all entity types and important entities present in the sample documents"},
            {"name": "Precision & Quality", "lens": "Focus on whether extracted entities are accurate, well-typed, and free of noise or hallucination"},
        ],
        output_dir=specs_dir / "general_golden",
        generator_model="claude-sonnet-4-6",
        judge_model="claude-sonnet-4-6",
        background=f"Sample documents are in {sample_dir}. Read them to understand what entity types exist in this corpus.",
        on_iteration=_make_iteration_recorder(job_id, "golden_set", db_path, str(specs_dir / "general_golden")),
        **bedrock_kwargs,
    )

    # Phase 2: Extraction spec simmering
    spec_result = await refine(
        artifact=golden_result.best_candidate,
        criteria={
            "coverage": "When run on sample docs, the spec finds all entities from the golden set",
            "precision": "Zero false positives",
            "format_compliance": "Output is valid JSON with name and type fields",
        },
        primary="coverage",
        iterations=settings.simmer_iterations,
        judge_mode="board",
        judge_panel=[
            {"name": "Coverage & Depth", "lens": "Focus on whether the spec captures all entity types and important entities present in the sample documents"},
            {"name": "Precision & Quality", "lens": "Focus on whether extracted entities are accurate, well-typed, and free of noise or hallucination"},
        ],
        output_dir=specs_dir / "general_spec",
        generator_model="claude-sonnet-4-6",
        judge_model="claude-sonnet-4-6",
        clerk_model="claude-haiku-4-5",
        background=f"This spec will be executed by Haiku. Golden set: {golden_result.best_candidate[:2000]}",
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
