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
        seed_content = f"""Starting from the general extraction spec (extend it with domain-specific types):

{general_spec[0]}

Now refine this for the specific domain: {domain_path}
Add entity types that are specific to this domain that the general spec misses.
Keep the general types but add domain-specific ones."""
    else:
        seed_content = f"""Entity types to extract for domain: {domain_path}
- Discover what entity types matter for this specific domain
- Be more specific than generic types like Person, Organization, Thing"""

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

    # Phase 1: Golden set simmering (domain-specific)
    golden_result = await refine(
        artifact=str(seed_path),
        criteria={
            "coverage": f"Captures all entity types specific to {domain_path} that the general spec misses",
            "precision": "No hallucinated entities, no noise — every entity is in the source text",
            "domain_specificity": f"Types are specific to {domain_path}, not just generic categories",
        },
        primary="coverage",
        iterations=settings.simmer_iterations,
        judge_mode="board",
        output_dir=domain_dir / "golden",
        generator_model="claude-sonnet-4-6",
        judge_model="claude-sonnet-4-6",
        background=f"Sample documents from domain '{domain_path}' are in {sample_dir}. Discover entity types specific to this domain.",
        on_iteration=_make_iteration_recorder(job_id, "golden_set", db_path, str(domain_dir / "golden")),
        **bedrock_kwargs,
    )

    # Phase 2: Extraction spec simmering
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
        output_dir=domain_dir / "spec",
        generator_model="claude-sonnet-4-6",
        judge_model="claude-sonnet-4-6",
        clerk_model="claude-haiku-4-5",
        background=f"This spec will be executed by Haiku on documents in domain '{domain_path}'. Golden set: {golden_result.best_candidate[:2000]}",
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
