"""General spec simmering via simmer-sdk, Firestore-aware.

Reads sample docs from Firestore, runs simmer refinement loop,
writes spec + iterations + criterion details back to Firestore.
"""
import os
import uuid
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from simmer_sdk import refine
from google.cloud import firestore


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


async def _parse_judgment_file(judgment_text: str, seed_scores: dict) -> list[dict]:
    """Use Haiku to extract per-criterion details from judgment."""
    from anthropic import AsyncAnthropicBedrock

    client = AsyncAnthropicBedrock(
        aws_access_key=os.environ.get("AWS_ACCESS_KEY", ""),
        aws_secret_key=os.environ.get("AWS_SECRET_KEY", ""),
        aws_region=os.environ.get("AWS_REGION", "us-east-1"),
    )

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
        model = os.environ.get("EXTRACTION_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
        response = await client.messages.create(
            model=model, max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(text)
    except Exception as e:
        print(f"  Judgment parse failed: {e}", flush=True)
        return []


def _make_iteration_recorder(db: firestore.Client, workspace_id: str, job_id: str, phase: str, output_dir: str):
    """Create an on_iteration callback that stores iteration data in Firestore."""
    seed_scores: dict[str, int] = {}
    iter_col = db.collection(f"workspaces/{workspace_id}/simmerIterations")
    detail_col = db.collection(f"workspaces/{workspace_id}/simmerCriterionDetails")

    async def on_iteration(record, trajectory, trajectory_table):
        nonlocal seed_scores

        if record.iteration == 0 or not seed_scores:
            seed_scores = dict(record.scores)

        iteration_id = str(uuid.uuid4())
        iter_col.document(iteration_id).set({
            "jobId": job_id,
            "phase": phase,
            "iteration": record.iteration,
            "scores": record.scores,
            "composite": record.composite,
            "keyChange": record.key_change,
            "asi": record.asi,
            "judgeMode": record.judge_mode,
            "regressed": record.regressed,
            "candidatePreview": None,
            "createdAt": datetime.now(timezone.utc),
        })

        # Parse judgment file for criterion details
        judgment_path = Path(output_dir) / f"iteration-{record.iteration}-judgment.md"
        if judgment_path.exists() and record.iteration > 0:
            judgment_text = judgment_path.read_text()
            details = await _parse_judgment_file(judgment_text, seed_scores)
            for d in details:
                detail_col.document(str(uuid.uuid4())).set({
                    "iterationId": iteration_id,
                    "criterion": d.get("criterion", ""),
                    "score": d.get("score", 0),
                    "seedScore": d.get("seed_score", 0),
                    "evidence": d.get("evidence", ""),
                    "improve": d.get("improve", ""),
                })
            if details:
                print(f"  [{phase}] iter {record.iteration}: parsed {len(details)} criterion details", flush=True)

        print(f"  [{phase}] iteration {record.iteration}: {record.composite}/10 — {record.key_change}", flush=True)

    return on_iteration


async def run_simmer_general(db: firestore.Client, workspace_id: str, job_id: str, job: dict):
    """Run general spec simmering."""
    # Get sample documents from Firestore
    doc_col = db.collection(f"workspaces/{workspace_id}/documents")
    docs = list(doc_col.where("status", "in", ["classified", "extracted", "enriched"]).limit(10).stream())

    if not docs:
        raise ValueError("No documents available to simmer general spec")

    # Write sample docs to temp directory (simmer-sdk reads from disk)
    with tempfile.TemporaryDirectory() as tmpdir:
        sample_dir = Path(tmpdir) / "samples"
        sample_dir.mkdir()
        for doc in docs:
            d = doc.to_dict()
            (sample_dir / f"{doc.id}.txt").write_text(d.get("content", ""))

        seed_path = Path(tmpdir) / "seed.md"
        seed_path.write_text(SEED_ONTOLOGY)

        bedrock_kwargs = {
            "api_provider": "bedrock",
            "aws_access_key": os.environ.get("AWS_ACCESS_KEY", ""),
            "aws_secret_key": os.environ.get("AWS_SECRET_KEY", ""),
            "aws_region": os.environ.get("AWS_REGION", "us-east-1"),
        }

        iterations = int(os.environ.get("SIMMER_ITERATIONS", "5"))
        golden_dir = Path(tmpdir) / "golden"
        spec_dir = Path(tmpdir) / "spec"

        print(f"Simmering general spec (job {job_id})", flush=True)

        # Phase 1: Golden set
        golden_result = await refine(
            artifact=str(seed_path),
            criteria={
                "coverage": "Captures all entity types present in sample documents",
                "precision": "No hallucinated entities, no noise",
                "taxonomy_quality": "Entity types are meaningful, consistent, and cover the domain",
            },
            primary="coverage",
            iterations=iterations,
            judge_mode="board",
            judge_panel=[
                {"name": "Coverage & Depth", "lens": "Focus on whether the spec captures all entity types and important entities present in the sample documents"},
                {"name": "Precision & Quality", "lens": "Focus on whether extracted entities are accurate, well-typed, and free of noise or hallucination"},
            ],
            output_dir=golden_dir,
            generator_model="claude-sonnet-4-6",
            judge_model="claude-sonnet-4-6",
            background=f"Sample documents are in {sample_dir}. Read them to understand what entity types exist in this corpus.",
            on_iteration=_make_iteration_recorder(db, workspace_id, job_id, "golden_set", str(golden_dir)),
            **bedrock_kwargs,
        )

        # Phase 2: Extraction spec
        spec_result = await refine(
            artifact=golden_result.best_candidate,
            criteria={
                "coverage": "When run on sample docs, the spec finds all entities from the golden set",
                "precision": "Zero false positives",
                "format_compliance": "Output is valid JSON with name and type fields",
            },
            primary="coverage",
            iterations=iterations,
            judge_mode="board",
            judge_panel=[
                {"name": "Coverage & Depth", "lens": "Focus on whether the spec captures all entity types and important entities present in the sample documents"},
                {"name": "Precision & Quality", "lens": "Focus on whether extracted entities are accurate, well-typed, and free of noise or hallucination"},
            ],
            output_dir=spec_dir,
            generator_model="claude-sonnet-4-6",
            judge_model="claude-sonnet-4-6",
            clerk_model="claude-haiku-4-5",
            background=f"This spec will be executed by Haiku. Golden set: {golden_result.best_candidate[:2000]}",
            on_iteration=_make_iteration_recorder(db, workspace_id, job_id, "extraction_spec", str(spec_dir)),
            **bedrock_kwargs,
        )

    # Store spec in Firestore
    spec_id = str(uuid.uuid4())
    spec_col = db.collection(f"workspaces/{workspace_id}/specs")
    spec_col.document(spec_id).set({
        "domainPath": None,  # general spec
        "version": 1,
        "specContent": spec_result.best_candidate,
        "goldenSet": golden_result.best_candidate,
        "score": spec_result.composite,
        "createdAt": datetime.now(timezone.utc),
    })

    # Queue batch extraction job
    batch_job_id = str(uuid.uuid4())
    job_col = db.collection(f"workspaces/{workspace_id}/jobs")
    job_col.document(batch_job_id).set({
        "type": "extract_batch",
        "target": "general",
        "status": "queued",
        "config": {"spec_id": spec_id, "scope": "all_classified"},
        "result": None,
        "createdAt": datetime.now(timezone.utc),
        "startedAt": None,
        "completedAt": None,
    })

    # Update job result
    job_ref = db.collection(f"workspaces/{workspace_id}/jobs").document(job_id)
    job_ref.update({
        "result": {
            "spec_id": spec_id,
            "golden_score": golden_result.composite,
            "spec_score": spec_result.composite,
            "batch_job_id": batch_job_id,
        }
    })

    print(f"General spec simmered! Score: {spec_result.composite}/10, queued batch extraction {batch_job_id}", flush=True)
