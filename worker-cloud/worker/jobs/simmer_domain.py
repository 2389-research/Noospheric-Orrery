"""Domain-specific spec simmering — refines extraction for one domain.

Same split pattern as general simmering:
  1. Golden set phase — refines entity types for this domain
  2. Extraction spec phase — refines the extraction prompt

Uses docs from the target domain only. Uses the general spec as the
starting artifact (not the generic seed ontology).
"""
import os
import uuid
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from simmer_sdk import refine
from google.cloud import firestore

# Reuse shared helpers from simmer_general
from worker.jobs.simmer_general import (
    _parse_judgment_file,
    _make_iteration_recorder,
    _get_bedrock_kwargs,
)


async def run_simmer_domain(db: firestore.Client, workspace_id: str, job_id: str, job: dict):
    """Run domain-specific simmering. Creates parent job, kicks off golden set phase."""
    domain_path = job.get("target", "")
    if not domain_path:
        raise ValueError("No target domain specified")

    print(f"Domain simmer (parent {job_id}): {domain_path}", flush=True)

    # Queue golden set child
    golden_job_id = str(uuid.uuid4())
    db.collection(f"workspaces/{workspace_id}/jobs").document(golden_job_id).set({
        "type": "simmer_domain_golden_set",
        "target": domain_path,
        "status": "queued",
        "parentJobId": job_id,
        "createdAt": datetime.now(timezone.utc),
    })

    db.collection(f"workspaces/{workspace_id}/jobs").document(job_id).update({
        "result": {"golden_set_job_id": golden_job_id, "phase": "golden_set"},
    })


async def run_simmer_domain_golden_set(db: firestore.Client, workspace_id: str, job_id: str, job: dict):
    """Golden set phase for a specific domain."""
    parent_job_id = job.get("parentJobId", job_id)
    domain_path = job.get("target", "")

    # Get docs for this domain only
    dd_col = db.collection(f"workspaces/{workspace_id}/documentDomains")
    doc_col = db.collection(f"workspaces/{workspace_id}/documents")

    domain_docs = list(dd_col.where("domainPath", "==", domain_path).limit(10).stream())
    doc_ids = [d.to_dict().get("documentId") for d in domain_docs]

    if not doc_ids:
        raise ValueError(f"No documents found for domain {domain_path}")

    with tempfile.TemporaryDirectory() as tmpdir:
        sample_dir = Path(tmpdir) / "samples"
        sample_dir.mkdir()
        for doc_id in doc_ids:
            doc = doc_col.document(doc_id).get()
            if doc.exists:
                content = doc.to_dict().get("content", "")
                (sample_dir / f"{doc_id}.txt").write_text(content)

        # Build seed from general spec with domain refinement instructions
        spec_col = db.collection(f"workspaces/{workspace_id}/specs")
        general_specs = list(spec_col.where("domainPath", "==", None).stream())
        if general_specs:
            general_content = max(general_specs, key=lambda s: s.to_dict().get("version", 0)).to_dict().get("specContent", "")
            seed_content = f"""Starting from the general extraction spec (extend it with domain-specific types):

{general_content}

Now refine this for the specific domain: {domain_path}
Add entity types that are specific to this domain that the general spec misses.
Keep the general types but add domain-specific ones."""
        else:
            seed_content = f"""Entity types to extract for domain: {domain_path}
- Discover what entity types matter for this specific domain
- Be more specific than generic types like Person, Organization, Thing"""

        seed_path = Path(tmpdir) / "seed.md"
        seed_path.write_text(seed_content)

        iterations = int(os.environ.get("SIMMER_ITERATIONS", "5"))
        golden_dir = Path(tmpdir) / "golden"

        print(f"Phase 1: Domain golden set for {domain_path} (child {job_id}, parent {parent_job_id})", flush=True)
        print(f"  {len(doc_ids)} docs, seed from general spec ({len(seed_content)} chars)", flush=True)

        golden_result = await refine(
            artifact=str(seed_path),
            criteria={
                "coverage": f"Captures all entity types present in {domain_path} documents",
                "precision": "No hallucinated entities, no noise",
                "domain_specificity": f"Entity types are specific to {domain_path}, not generic",
            },
            primary="coverage",
            iterations=iterations,
            judge_mode="board",
            judge_panel=[
                {"name": "Coverage & Depth", "lens": f"Focus on entity types specific to {domain_path}"},
                {"name": "Precision & Quality", "lens": "Focus on whether extracted entities are accurate and domain-specific"},
            ],
            output_dir=golden_dir,
            generator_model="claude-sonnet-4-6",
            judge_model="claude-sonnet-4-6",
            background=f"Sample documents from domain '{domain_path}' are in {sample_dir}. Read them to understand what domain-specific entity types exist.",
            on_iteration=_make_iteration_recorder(db, workspace_id, parent_job_id, "golden_set", str(golden_dir)),
            **_get_bedrock_kwargs(),
        )

    # Save golden set
    golden_ref = db.collection(f"workspaces/{workspace_id}/specs").document(f"golden_set_{domain_path.replace('/', '_')}")
    golden_ref.set({
        "type": "golden_set",
        "domainPath": domain_path,
        "content": golden_result.best_candidate,
        "score": golden_result.composite,
        "bestIteration": golden_result.best_iteration,
        "createdAt": datetime.now(timezone.utc),
        "jobId": parent_job_id,
    })

    # Queue extraction spec phase
    spec_job_id = str(uuid.uuid4())
    db.collection(f"workspaces/{workspace_id}/jobs").document(spec_job_id).set({
        "type": "simmer_domain_extraction_spec",
        "target": domain_path,
        "status": "queued",
        "parentJobId": parent_job_id,
        "createdAt": datetime.now(timezone.utc),
    })

    db.collection(f"workspaces/{workspace_id}/jobs").document(parent_job_id).update({
        "result": {
            "golden_score": golden_result.composite,
            "golden_set_job_id": job_id,
            "extraction_spec_job_id": spec_job_id,
            "phase": "extraction_spec",
        }
    })

    print(f"Domain golden set complete! Score: {golden_result.composite}/10", flush=True)


async def run_simmer_domain_extraction_spec(db: firestore.Client, workspace_id: str, job_id: str, job: dict):
    """Extraction spec phase for a specific domain."""
    parent_job_id = job.get("parentJobId", job_id)
    domain_path = job.get("target", "")

    # Read domain golden set
    golden_doc = db.collection(f"workspaces/{workspace_id}/specs").document(f"golden_set_{domain_path.replace('/', '_')}").get()
    if not golden_doc.exists:
        raise ValueError(f"No golden set found for domain {domain_path}")

    golden_data = golden_doc.to_dict()
    golden_content = golden_data["content"]

    # Get domain docs
    dd_col = db.collection(f"workspaces/{workspace_id}/documentDomains")
    doc_col = db.collection(f"workspaces/{workspace_id}/documents")
    domain_docs = list(dd_col.where("domainPath", "==", domain_path).limit(10).stream())
    doc_ids = [d.to_dict().get("documentId") for d in domain_docs]

    with tempfile.TemporaryDirectory() as tmpdir:
        sample_dir = Path(tmpdir) / "samples"
        sample_dir.mkdir()
        for doc_id in doc_ids:
            doc = doc_col.document(doc_id).get()
            if doc.exists:
                (sample_dir / f"{doc_id}.txt").write_text(doc.to_dict().get("content", ""))

        iterations = int(os.environ.get("SIMMER_ITERATIONS", "5"))
        spec_dir = Path(tmpdir) / "spec"

        print(f"Phase 2: Domain extraction spec for {domain_path} (child {job_id}, parent {parent_job_id})", flush=True)

        spec_result = await refine(
            artifact=golden_content,
            criteria={
                "coverage": f"Finds all {domain_path}-specific entities from the golden set",
                "precision": "Zero false positives",
                "format_compliance": "Output is valid JSON with name and type fields",
            },
            primary="coverage",
            iterations=iterations,
            judge_mode="board",
            judge_panel=[
                {"name": "Coverage & Depth", "lens": f"Focus on domain-specific entities for {domain_path}"},
                {"name": "Precision & Quality", "lens": "Focus on accuracy and domain specificity"},
            ],
            output_dir=spec_dir,
            generator_model="claude-sonnet-4-6",
            judge_model="claude-sonnet-4-6",
            clerk_model="claude-haiku-4-5",
            background=f"This spec extracts entities for domain '{domain_path}'. Golden set: {golden_content[:2000]}",
            on_iteration=_make_iteration_recorder(db, workspace_id, parent_job_id, "extraction_spec", str(spec_dir)),
            **_get_bedrock_kwargs(),
        )

    # Store domain spec
    spec_id = str(uuid.uuid4())
    db.collection(f"workspaces/{workspace_id}/specs").document(spec_id).set({
        "domainPath": domain_path,
        "version": 1,
        "specContent": spec_result.best_candidate,
        "goldenSet": golden_content,
        "score": spec_result.composite,
        "createdAt": datetime.now(timezone.utc),
    })

    # Update domain record with spec version
    domain_col = db.collection(f"workspaces/{workspace_id}/domains")
    encoded = domain_path.replace("/", "__")
    domain_col.document(encoded).update({"specVersion": 1})

    # Mark parent completed
    db.collection(f"workspaces/{workspace_id}/jobs").document(parent_job_id).update({
        "status": "completed",
        "completedAt": datetime.now(timezone.utc),
        "result": {
            "spec_id": spec_id,
            "golden_score": golden_data.get("score"),
            "spec_score": spec_result.composite,
            "phase": "completed",
        }
    })

    print(f"Domain extraction spec complete! Score: {spec_result.composite}/10 for {domain_path}", flush=True)
