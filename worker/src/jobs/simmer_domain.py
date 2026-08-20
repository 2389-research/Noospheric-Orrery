# ABOUTME: Domain-specific spec simmering job — refines extraction spec for a single domain.
# ABOUTME: Starts from the general spec and adds domain-specific entity types via simmer-sdk.

import re
import shlex
import uuid
import json
from pathlib import Path
from simmer_sdk import refine
from ..db import get_connection
from ..config import get_settings
from .simmer_general import _build_golden_set_judged, _refine_spec_rules, _discover_domain_types, BASE_TAXONOMY


def _authored_spec_for(conn, domain_path: str) -> str | None:
    """Return the latest AUTHORED spec body for this domain, or None.

    Only authored specs are returned. A simmered spec is additive and is not a seed —
    seeding from one would just re-refine what the last run already produced.
    """
    row = conn.execute(
        "SELECT spec_content, source FROM specs WHERE domain_path = ? "
        "ORDER BY version DESC LIMIT 1", (domain_path,)).fetchone()
    if not row or (row[1] or "simmered") != "authored":
        return None
    return row[0]


def _build_seed_content(domain_path: str, general_spec: str | None,
                        authored_spec: str | None) -> str:
    """Build the golden-set seed.

    Two contracts, two framings, and they must not be mixed up:

      - AUTHORED: a domain expert has declared the entity types. Their types are FIXED;
        simmer refines only the wording and the examples. The spec stays COMPLETE, because
        an authored spec suppresses the general extraction pass (see
        orchestrator/src/pipeline/extraction_plan.py) and must therefore stand alone.
      - Otherwise: the historical additive framing — discover MORE GRANULAR types on top of
        the general spec, which still runs alongside.
    """
    reference_block = """## Reference Entities

Read every sample document and list ALL entities you find. Each entity must actually
appear in at least one sample document — do not invent entities.

Format as a JSON array:
```json
[
  {"name": "entity name lowercase", "type": "EntityType"},
  ...
]
```"""

    if authored_spec:
        return f"""# Golden Set — Domain: {domain_path}

## Entity Type Taxonomy
A domain expert authored the extraction rules below. This spec is COMPLETE: it is the only
spec that runs for this domain, so it must stand alone. Do NOT add entity types the expert
did not declare, and do NOT remove any they did. Refine only the wording, the boundaries,
and the examples.

{authored_spec}

{reference_block}"""

    if general_spec:
        return f"""# Golden Set — Domain: {domain_path}

## Entity Type Taxonomy
Starting from the general extraction spec, extend with domain-specific types:

{general_spec}

Add entity types specific to {domain_path} that the general spec misses.
Keep the general types but add domain-specific ones.

{reference_block}

Be thorough — every named person, organization, product, concept, place, and event
mentioned in the sample documents should appear here."""

    return f"""# Golden Set — Domain: {domain_path}

## Entity Type Taxonomy
- Discover what entity types matter for this specific domain
- Be more specific than generic types like Person, Organization, Thing

{reference_block}"""


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

    # An AUTHORED spec is a domain expert's declaration: it seeds the loop and its entity
    # types are fixed. Otherwise fall back to the historical additive framing on top of
    # the general spec.
    authored_spec = _authored_spec_for(conn, domain_path)
    general_row = conn.execute(
        "SELECT spec_content FROM specs WHERE domain_path IS NULL ORDER BY version DESC LIMIT 1"
    ).fetchone()
    seed_content = _build_seed_content(
        domain_path,
        general_spec=general_row[0] if general_row else None,
        authored_spec=authored_spec,
    )

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

    # Domain refinement is ADDITIVE: discover MORE GRANULAR, domain-specific entity types and
    # extract ONLY those (base types are covered by the general pass). The positive "extract only
    # these types" constraint excludes base types on its own. Dedup/canonicalization is the
    # normalization step's job (issue #26).
    if resume and golden_set_path.exists():
        # Reuse the cached golden AND the taxonomy embedded in it, so Phase 2 scores against a
        # consistent taxonomy (discovery is non-deterministic — don't re-roll it on resume).
        golden_best = golden_set_path.read_text()
        m = re.search(r"## Entity Type Taxonomy\n(.*?)\n\n## Reference Entities", golden_best, re.DOTALL)
        domain_taxonomy = m.group(1).strip() if m else BASE_TAXONOMY
        print(f"Resuming domain spec for {domain_path} — reusing cached golden ({len(golden_best)} chars, job {job_id})", flush=True)
    else:
        if authored_spec:
            # The expert declared the types. There is nothing to discover, and the
            # early-return below (which exists to avoid storing a redundant generic spec)
            # must not fire — an authored refinement always has something to refine.
            domain_taxonomy = authored_spec
            mode = "authored, complete"
        else:
            domain_types = await _discover_domain_types(sample_chunks, domain_path, settings, db_path)
            n_domain = len(domain_types.splitlines()) if domain_types else 0
            print(f"Domain types for {domain_path}: +{n_domain}\n{domain_types}", flush=True)
            if not domain_types:
                # Nothing domain-specific to add → domain refinement has no value here. Skip rather
                # than store a generic spec that just re-does the base types the general pass covers.
                print(f"No domain-specific types discovered for {domain_path}; skipping domain refinement.", flush=True)
                return
            domain_taxonomy = domain_types
            mode = f"additive, {n_domain} domain types"
        print(f"Building domain golden via judged loop ({mode}): {domain_path} ({len(sample_chunks)} chunks, {iterations} iters, job {job_id})", flush=True)
        golden_best = await _build_golden_set_judged(
            sample_chunks, settings, job_id, db_path, iterations,
            taxonomy_hint=domain_taxonomy, domain_path=domain_path)
        golden_set_path.write_text(golden_best)

    # Phase 2: decomposed rules-spec. Without an authored spec this is ADDITIVE — it extracts
    # the granular domain entities and the general spec handles the base types. With one, the
    # taxonomy is the expert's own and the result must stay COMPLETE, because an authored spec
    # suppresses the general pass entirely (orchestrator/src/pipeline/extraction_plan.py).
    print(f"Refining {domain_path} extraction-spec rules ({len(sample_chunks)} chunks, job {job_id})", flush=True)
    spec_content, spec_score = await _refine_spec_rules(
        golden_best, sample_chunks, settings, job_id, db_path, iterations,
        domain_path=domain_path, taxonomy=domain_taxonomy,
    )

    # Store spec
    conn = get_connection(db_path)

    # Get next version for this domain
    existing_version = conn.execute(
        "SELECT MAX(version) FROM specs WHERE domain_path = ?", (domain_path,)
    ).fetchone()[0]
    version = (existing_version or 0) + 1

    spec_id = str(uuid.uuid4())
    # The refined spec INHERITS the authored contract. Storing it as 'simmered' would flip
    # the general pass back on and silently undo the expert's exclusions.
    spec_source = "authored" if authored_spec else "simmered"
    conn.execute(
        "INSERT INTO specs (id, domain_path, version, spec_content, golden_set, score, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (spec_id, domain_path, version, spec_content, golden_best, spec_score, spec_source),
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
