# ABOUTME: Domain-specific spec simmering job — refines extraction spec for a single domain.
# ABOUTME: Starts from the general spec and adds domain-specific entity types via simmer-sdk.

import shlex
import uuid
import json
from pathlib import Path
from simmer_sdk import refine
from ..db import get_connection
from ..config import get_settings
from .simmer_general import _build_golden_set_mapreduce, _refine_spec_rules


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
    iterations = config.get("iterations", settings.simmer_iterations)

    conn = get_connection(db_path)

    # Sample chunks from documents in this domain (stratified across docs)
    sample_chunks = conn.execute(
        """SELECT c.id, c.text, d.title FROM chunks c
           JOIN documents d ON c.document_id = d.id
           JOIN document_domains dd ON d.id = dd.document_id
           WHERE dd.domain_path = ? AND d.status IN ('classified', 'extracted', 'enriched')
           ORDER BY RANDOM() LIMIT 10""",
        (domain_path,),
    ).fetchall()

    if not sample_chunks:
        conn.close()
        raise ValueError(f"No chunks in domain {domain_path}")

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

    # Write sample chunks and seed
    specs_dir = Path(settings.specs_dir)
    domain_dir = specs_dir / f"domain_{domain_path.replace('/', '_')}"
    domain_dir.mkdir(parents=True, exist_ok=True)
    sample_dir = domain_dir / "samples"
    # Clear old samples so only this run's chunks are used
    if sample_dir.exists():
        for old_file in sample_dir.glob("*.txt"):
            old_file.unlink()
    sample_dir.mkdir(exist_ok=True)

    for chunk in sample_chunks:
        # chunk row: (id, text, title)
        content = f"[Source: {chunk[2]}]\n\n{chunk[1]}"
        (sample_dir / f"{chunk[0]}.txt").write_text(content)

    seed_path = domain_dir / "seed.md"
    seed_path.write_text(seed_content)
    conn.close()

    # LLM provider config
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
    resume = config.get("resume", False)
    golden_set_path = domain_dir / "golden_set.md"

    # Phase 1: Golden set simmering (domain-specific) — type taxonomy + reference entities
    # Skip if resuming and a golden set already exists from a previous run
    if resume and golden_set_path.exists():
        golden_best = golden_set_path.read_text()
        print(f"Resuming domain spec for: {domain_path} — reusing existing golden set ({len(golden_best)} chars, job {job_id})", flush=True)
    else:
        # Phase 1: DECOMPOSED map-reduce golden generation (shared with simmer_general).
        # The old agentic refine() stalls on local models (gemma4:26b loops on the read tool
        # → empty candidate). map (e4b per-chunk extraction) → reduce (gemma4 canonicalize).
        # NOTE: uses the generic 6-type taxonomy rather than discovering domain-specific types;
        # domain-specificity is added in the Phase 2 spec rules instead.
        print(f"Building domain golden set via map-reduce: {domain_path} ({len(sample_chunks)} chunks, job {job_id})", flush=True)
        golden_best = await _build_golden_set_mapreduce(sample_chunks, settings, job_id, db_path)
        golden_set_path.write_text(golden_best)

    # Phase 2: DECOMPOSED rules-spec generation (shared with simmer_general). Produces a
    # GENERALIZED, domain-aware rules spec scored by F1 against the golden — no agentic
    # generator (which relisted golden entities on local models) and no LLM judge.
    print(f"Refining {domain_path} extraction-spec rules ({len(sample_chunks)} chunks, job {job_id})", flush=True)
    spec_content, spec_score = await _refine_spec_rules(
        golden_best, sample_chunks, settings, job_id, db_path, iterations, domain_path=domain_path,
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
        (spec_id, domain_path, version, spec_content, golden_best, spec_score),
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
    print(f"Domain spec for {domain_path}: v{version}, score {spec_score}/10 (rules-loop)", flush=True)
