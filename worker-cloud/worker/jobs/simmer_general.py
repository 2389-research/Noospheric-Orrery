"""General spec simmering via simmer-sdk, Firestore-aware.

Split into two independent phases that run as separate Cloud Run Jobs:
  1. simmer_golden_set — refines the entity taxonomy
  2. simmer_extraction_spec — refines the extraction prompt

A parent simmer_general job tracks the whole flow. Both phases write
iterations to the parent job so the UI shows them as one unified run.
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


def _make_iteration_recorder(db: firestore.Client, workspace_id: str, parent_job_id: str, phase: str, output_dir: str):
    """Create an on_iteration callback that stores iteration data under the parent job."""
    seed_scores: dict[str, int] = {}
    iter_col = db.collection(f"workspaces/{workspace_id}/simmerIterations")
    detail_col = db.collection(f"workspaces/{workspace_id}/simmerCriterionDetails")

    async def on_iteration(record, trajectory, trajectory_table):
        nonlocal seed_scores

        if record.iteration == 0 or not seed_scores:
            seed_scores = dict(record.scores)

        iteration_id = str(uuid.uuid4())
        iter_col.document(iteration_id).set({
            "jobId": parent_job_id,
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


def _get_sample_dir(db: firestore.Client, workspace_id: str, tmpdir: str) -> Path:
    """Write sample docs to temp directory for simmer-sdk."""
    doc_col = db.collection(f"workspaces/{workspace_id}/documents")
    docs = list(doc_col.where("status", "in", ["classified", "extracted", "enriched"]).limit(10).stream())

    if not docs:
        raise ValueError("No documents available for simmering")

    sample_dir = Path(tmpdir) / "samples"
    sample_dir.mkdir()
    for doc in docs:
        d = doc.to_dict()
        (sample_dir / f"{doc.id}.txt").write_text(d.get("content", ""))

    return sample_dir


def _get_bedrock_kwargs():
    return {
        "api_provider": "bedrock",
        "aws_access_key": os.environ.get("AWS_ACCESS_KEY", ""),
        "aws_secret_key": os.environ.get("AWS_SECRET_KEY", ""),
        "aws_region": os.environ.get("AWS_REGION", "us-east-1"),
    }


# ── Parent: Simmer General ────────────────────────────────────

async def run_simmer_general(db: firestore.Client, workspace_id: str, job_id: str, job: dict):
    """Create parent tracking job and kick off golden set phase.

    The parent job stays in 'running' status while child phases execute.
    Iterations from both phases are written to the parent job ID.
    """
    # This job IS the parent — kick off golden set as first phase
    print(f"Simmer general (parent {job_id}): starting golden set phase", flush=True)

    # Queue golden set child job
    golden_job_id = str(uuid.uuid4())
    db.collection(f"workspaces/{workspace_id}/jobs").document(golden_job_id).set({
        "type": "simmer_golden_set",
        "target": "general",
        "status": "queued",
        "parentJobId": job_id,
        "createdAt": datetime.now(timezone.utc),
    })

    # Update parent with child reference
    db.collection(f"workspaces/{workspace_id}/jobs").document(job_id).update({
        "result": {"golden_set_job_id": golden_job_id, "phase": "golden_set"},
    })

    # Don't mark parent as completed — it stays running until the whole chain finishes


# ── Phase 1: Golden Set ──────────────────────────────────────

async def run_simmer_golden_set(db: firestore.Client, workspace_id: str, job_id: str, job: dict):
    """Run golden set refinement. Writes iterations to parent job."""
    parent_job_id = job.get("parentJobId", job_id)

    with tempfile.TemporaryDirectory() as tmpdir:
        sample_dir = _get_sample_dir(db, workspace_id, tmpdir)
        seed_path = Path(tmpdir) / "seed.md"
        seed_path.write_text(SEED_ONTOLOGY)

        iterations = int(os.environ.get("SIMMER_ITERATIONS", "5"))
        golden_dir = Path(tmpdir) / "golden"

        print(f"Phase 1: Golden set (child {job_id}, parent {parent_job_id})", flush=True)

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
            on_iteration=_make_iteration_recorder(db, workspace_id, parent_job_id, "golden_set", str(golden_dir)),
            **_get_bedrock_kwargs(),
        )

    # Save golden set artifact
    golden_ref = db.collection(f"workspaces/{workspace_id}/specs").document("golden_set_latest")
    golden_ref.set({
        "type": "golden_set",
        "content": golden_result.best_candidate,
        "score": golden_result.composite,
        "bestIteration": golden_result.best_iteration,
        "createdAt": datetime.now(timezone.utc),
        "jobId": parent_job_id,
    })

    # Queue extraction spec phase (child of same parent)
    spec_job_id = str(uuid.uuid4())
    db.collection(f"workspaces/{workspace_id}/jobs").document(spec_job_id).set({
        "type": "simmer_extraction_spec",
        "target": "general",
        "status": "queued",
        "parentJobId": parent_job_id,
        "config": {"golden_set_job_id": job_id},
        "createdAt": datetime.now(timezone.utc),
    })

    # Update parent
    db.collection(f"workspaces/{workspace_id}/jobs").document(parent_job_id).update({
        "result": {
            "golden_score": golden_result.composite,
            "golden_set_job_id": job_id,
            "extraction_spec_job_id": spec_job_id,
            "phase": "extraction_spec",
        }
    })

    print(f"Golden set complete! Score: {golden_result.composite}/10, queued extraction spec {spec_job_id}", flush=True)


# ── Phase 2: Extraction Spec ─────────────────────────────────

async def run_simmer_extraction_spec(db: firestore.Client, workspace_id: str, job_id: str, job: dict):
    """Run extraction spec refinement. Writes iterations to parent job."""
    parent_job_id = job.get("parentJobId", job_id)

    # Read golden set from Firestore
    golden_doc = db.collection(f"workspaces/{workspace_id}/specs").document("golden_set_latest").get()
    if not golden_doc.exists:
        raise ValueError("No golden set found — run simmer_golden_set first")

    golden_data = golden_doc.to_dict()
    golden_content = golden_data["content"]
    print(f"Using golden set (score {golden_data.get('score')})", flush=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        sample_dir = _get_sample_dir(db, workspace_id, tmpdir)

        iterations = int(os.environ.get("SIMMER_ITERATIONS", "5"))
        spec_dir = Path(tmpdir) / "spec"

        print(f"Phase 2: Extraction spec (child {job_id}, parent {parent_job_id})", flush=True)

        spec_result = await refine(
            artifact=golden_content,
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
            background=f"This spec will be executed by Haiku. Golden set: {golden_content[:2000]}",
            on_iteration=_make_iteration_recorder(db, workspace_id, parent_job_id, "extraction_spec", str(spec_dir)),
            **_get_bedrock_kwargs(),
        )

    # Store final spec
    spec_id = str(uuid.uuid4())
    db.collection(f"workspaces/{workspace_id}/specs").document(spec_id).set({
        "domainPath": None,
        "version": 1,
        "specContent": spec_result.best_candidate,
        "goldenSet": golden_content,
        "score": spec_result.composite,
        "createdAt": datetime.now(timezone.utc),
    })

    # Queue batch extraction
    batch_job_id = str(uuid.uuid4())
    db.collection(f"workspaces/{workspace_id}/jobs").document(batch_job_id).set({
        "type": "extract_batch",
        "target": "general",
        "status": "queued",
        "parentJobId": parent_job_id,
        "config": {"spec_id": spec_id, "scope": "all_classified"},
        "result": None,
        "createdAt": datetime.now(timezone.utc),
    })

    # Update parent — mark as completed with full results
    db.collection(f"workspaces/{workspace_id}/jobs").document(parent_job_id).update({
        "status": "completed",
        "completedAt": datetime.now(timezone.utc),
        "result": {
            "spec_id": spec_id,
            "golden_score": golden_data.get("score"),
            "spec_score": spec_result.composite,
            "batch_job_id": batch_job_id,
            "phase": "completed",
        }
    })

    print(f"Extraction spec complete! Score: {spec_result.composite}/10, queued batch extraction {batch_job_id}", flush=True)
