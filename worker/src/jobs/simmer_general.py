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


SEED_IMAGE_GOLDEN_SET = """# Image Golden Set

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

## Reference Observations

Look at every sample image and for EACH image record:
1. ALL visual entities (name + type from taxonomy above)
2. A 2-3 sentence description: first sentence = medium + subject, second = visual details, third = context
3. Searchable tags (categories, mood, use-case — not just entity name repeats)
4. medium, shot_type, and representation

Format as a JSON array — one entry per image:
```json
[
  {
    "image": "filename",
    "entities": [{"name": "entity name lowercase", "type": "EntityType"}, ...],
    "description": "2-3 sentence description",
    "tags": ["category", "mood", "use-case"],
    "medium": "photograph | painting | illustration | diagram | screenshot | other",
    "shot_type": "product shot | close-up | wide angle | macro | portrait | candid | aerial | other",
    "representation": "direct | painted miniature | oil painting | scale model | other"
  },
  ...
]
```

The reference list is the ground truth for image extraction. Be thorough — every identifiable
subject, object, person, text, and setting should appear. Descriptions must be accurate enough
that someone searching for the image content would find it from the description alone.
"""


GOLDEN_TAXONOMY = """- Person — people, speakers, authors, creators
- Organization — companies, groups, teams, brands
- Topic — concepts, ideas, theories, fields, subjects
- Event — happenings, milestones, dates, releases
- Location — places, regions, settings, venues
- Thing — objects, tools, products, materials, artifacts"""

GOLDEN_MAP_PROMPT = """You are an entity extraction system. Extract EVERY real named entity from the text below.

Entity type taxonomy:
{tax}

TEXT:
{chunk}

Rules:
- Extract only entities explicitly present in THIS text — do not invent.
- Normalize names: lowercase, strip whitespace.
- Be exhaustive about REAL entities: every named person, org, product, place, event, concept.
- DO NOT extract metadata as entities: no bare dates/timestamps, no filenames, no UUIDs/IDs, no URLs, no raw numbers."""

GOLDEN_MAP_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "type": {"type": "string"}},
                "required": ["name", "type"],
            },
        }
    },
    "required": ["entities"],
}


GOLDEN_CANON_PROMPT = """You are canonicalizing a list of "{etype}" entities extracted from documents. Because each document was processed independently, the list has duplicates and noise. Produce a CLEAN canonical list of {etype} names.

Rules:
- FRAGMENTS: merge a partial name into its fuller form ("harper" + "harper reed" -> "harper reed"; "russ" + "russell cummer" -> "russell cummer").
- SPELLING VARIANTS / TYPOS: merge to the correct form ("commer corporation" + "cummer corporation" -> "cummer corporation"; "vancouv" + "vancouver" -> "vancouver").
- ACRONYM / EXPANSION: keep ONE canonical form ("lvmh" and "louis vuitton moet hennessy" are the same — keep one); merge garbled variants into it.
- NEAR-DUPLICATES: collapse trivial variants ("ecommerce" / "e-commerce" -> one).
- DROP NON-ENTITIES: remove emails and vague phrase-fragments that aren't real named entities ("ease of purchasing", "pay for play", "market expansion plans").
- Do NOT invent new names; only merge or drop.

{etype} NAMES ({n} items):
{listing}"""

GOLDEN_CANON_SCHEMA = {
    "type": "object",
    "properties": {"names": {"type": "array", "items": {"type": "string"}}},
    "required": ["names"],
}


async def _canonicalize_group(group: list[dict], etype: str, relay: Relay, model: str) -> list[dict]:
    """Canonicalize one type's entities. Merging within a type is correct (you never merge
    a Person into an Organization), and keeps each call's output within the token budget."""
    if len(group) < 2:
        return group
    listing = "\n".join(f"- {e['name']}" for e in group)
    try:
        result = await relay.complete_structured(
            model=model, max_tokens=4096,
            messages=[{"role": "user", "content": GOLDEN_CANON_PROMPT.format(etype=etype, n=len(group), listing=listing)}],
            schema=GOLDEN_CANON_SCHEMA,
            tool_name="canonical_names",
            tool_description=f"Return the cleaned canonical {etype} names",
        )
        cleaned = result.get("names", []) if isinstance(result, dict) else []
        out, seen = [], set()
        for n in cleaned:
            name = str(n).lower().strip()
            if name and name not in seen:
                seen.add(name)
                out.append({"name": name, "type": etype})
        # Safety: reject a degenerate result (empty, or larger than input — likely a parse failure)
        if not out or len(out) > len(group):
            print(f"  [golden_set] canon {etype}: {len(out)} (raw {len(group)}) — keeping raw", flush=True)
            return group
        return out
    except Exception as e:
        print(f"  [golden_set] canon {etype} failed, keeping raw: {e}", flush=True)
        return group


async def _canonicalize_golden(golden: list[dict], relay: Relay, model: str) -> list[dict]:
    """REDUCE: LLM canonicalization that merges fragments/variants/acronyms and drops
    non-entities — the global view per-chunk extraction lacks. Batched PER TYPE so each
    call stays within the output-token budget (one call over hundreds of entities overflows
    and parse-fails). Falls back to the raw group on any failure."""
    if len(golden) < 2:
        return golden
    from collections import defaultdict
    by_type: dict[str, list[dict]] = defaultdict(list)
    for e in golden:
        by_type[e["type"]].append(e)
    out: list[dict] = []
    for etype, group in by_type.items():
        out.extend(await _canonicalize_group(group, etype, relay, model))
    return sorted(out, key=lambda e: (e["type"], e["name"]))


async def _build_golden_set_mapreduce(sample_chunks, settings, job_id: str, db_path: str) -> str:
    """Decomposed golden-set generation for local models.

    MAP: one small extraction call per chunk (no tools, no agentic loop).
    REDUCE: pure-Python merge + dedupe across chunks.

    Replaces the agentic refine() generator, which stalls on local models
    (gemma4:26b loops on the read tool → empty candidate). Deterministic.
    """
    relay = Relay.from_settings(settings)
    extract_model = settings.extraction_model       # e4b — fast, purpose-built per-chunk extraction (MAP)
    canon_model = settings.classification_model      # 26b — global reasoning for canonicalization (REDUCE)
    merged: dict[tuple, dict] = {}
    per_chunk = []
    for chunk in sample_chunks:
        text = chunk[1]  # (id, text, title)
        try:
            result = await relay.complete_structured(
                model=extract_model, max_tokens=2048,
                messages=[{"role": "user", "content": GOLDEN_MAP_PROMPT.format(tax=GOLDEN_TAXONOMY, chunk=text)}],
                schema=GOLDEN_MAP_SCHEMA,
                tool_name="extract_entities",
                tool_description="Extract named entities from the text",
            )
            ents = result.get("entities", []) if isinstance(result, dict) else []
        except Exception as e:
            print(f"  [golden_set map] chunk error: {e}", flush=True)
            ents = []
        per_chunk.append(len(ents))
        for e in ents:
            name = str(e.get("name", "")).lower().strip()
            etype = str(e.get("type", "")).strip().capitalize()
            if name and (name, etype) not in merged:
                merged[(name, etype)] = {"name": name, "type": etype}

    golden = sorted(merged.values(), key=lambda e: (e["type"], e["name"]))
    print(f"  [golden_set] map: {len(golden)} entities from {len(sample_chunks)} chunks (per-chunk: {per_chunk})", flush=True)

    # REDUCE: LLM canonicalization. Per-chunk extraction has no global view, so fragments
    # ("harper"/"harper reed"), spelling/typo variants ("commer"/"cummer"), acronym pairs
    # ("lvmh"/"louis vuitton moet hennessy") and non-entities (emails, vague phrases) survive
    # the exact-match merge above. One bounded gemma4 call canonicalizes them — recovering the
    # global dedup a single-context (agentic) pass does, without the agentic fragility.
    raw_count = len(golden)
    golden = await _canonicalize_golden(golden, relay, canon_model)
    print(f"  [golden_set] reduce (canonicalize): {raw_count} -> {len(golden)} entities", flush=True)

    md = "\n".join([
        "# Golden Set\n",
        "## Entity Type Taxonomy",
        GOLDEN_TAXONOMY,
        "\n## Reference Entities\n",
        "```json",
        json.dumps(golden, indent=2),
        "```",
    ])

    # Record one golden_set iteration row so the trajectory/monitor shows the phase
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO simmer_iterations (id, job_id, phase, iteration, scores, composite, key_change, asi, judge_mode, regressed, candidate_preview) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), job_id, "golden_set", 0, json.dumps({}), None,
             f"map-reduce decomposed generation: {len(golden)} entities (no agentic loop)",
             None, "map-reduce", False, None),
        )
        conn.commit()
    finally:
        conn.close()

    return md


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
                    # Backfill correct scores from criterion_details (simmer-sdk safety net)
                    real_scores = {d["criterion"]: d["score"] for d in details if d.get("score")}
                    if real_scores:
                        real_composite = round(sum(real_scores.values()) / len(real_scores), 1)
                        conn.execute(
                            "UPDATE simmer_iterations SET scores = ?, composite = ? WHERE id = ?",
                            (json.dumps(real_scores), real_composite, iteration_id),
                        )

                    conn.commit()
                    print(f"  [{phase}] iter {record.iteration}: parsed {len(details)} criterion details", flush=True)
                finally:
                    conn.close()

        print(f"  [{phase}] iteration {record.iteration}: {record.composite}/10 — {record.key_change}", flush=True)
    return on_iteration


async def run_simmer_general(job: dict, db_path: str) -> None:
    settings = get_settings()
    config = json.loads(job["config"]) if job.get("config") else {}
    iterations = config.get("iterations", settings.simmer_iterations)
    conn = get_connection(db_path)

    # Sample chunks (stratified across documents) instead of full docs
    sample_chunks = conn.execute(
        """SELECT c.id, c.text, d.title FROM chunks c
           JOIN documents d ON c.document_id = d.id
           WHERE d.status IN ('classified', 'extracted')
           ORDER BY RANDOM() LIMIT 20"""
    ).fetchall()

    if not sample_chunks:
        conn.close()
        raise ValueError("No chunks available to simmer general spec")

    specs_dir = Path(settings.specs_dir)
    specs_dir.mkdir(parents=True, exist_ok=True)
    sample_dir = specs_dir / "general_samples"
    # Clear old samples so only this run's chunks are used
    if sample_dir.exists():
        for old_file in sample_dir.glob("*.txt"):
            old_file.unlink()
    sample_dir.mkdir(exist_ok=True)

    for chunk in sample_chunks:
        # chunk row: (id, text, title)
        content = f"[Source: {chunk[2]}]\n\n{chunk[1]}"
        (sample_dir / f"{chunk[0]}.txt").write_text(content)

    seed_path = specs_dir / "general_seed.md"
    seed_path.write_text(SEED_GOLDEN_SET)
    conn.close()

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
    golden_set_path = specs_dir / "general_golden_set.md"

    # Phase 1: Golden set simmering — produces type taxonomy + reference entity list
    # Skip if resuming and a golden set already exists from a previous run
    if resume and golden_set_path.exists():
        golden_best = golden_set_path.read_text()
        print(f"Resuming general spec — reusing existing golden set ({len(golden_best)} chars, job {job_id})", flush=True)
    else:
        # Phase 1 uses DECOMPOSED map-reduce generation instead of the agentic
        # refine() loop. Local models (gemma4:26b) stall in the agentic generator
        # — they loop on the read tool and emit an empty candidate. Map-reduce is
        # deterministic: one small extraction call per chunk, then a Python merge.
        print(f"Building golden set via map-reduce ({len(sample_chunks)} chunks, job {job_id})", flush=True)
        golden_best = await _build_golden_set_mapreduce(sample_chunks, settings, job_id, db_path)
        golden_set_path.write_text(golden_best)

    # Phase 2: Extraction spec simmering (with empirical evaluator)
    evaluator_script = Path(__file__).resolve().parent / "evaluate_spec.py"

    spec_result = await refine(
        artifact=golden_best,
        criteria={
            "coverage": "When run on sample docs, the spec finds all entities from the golden set",
            "precision": "Zero false positives",
            "generalizability": "The spec uses general rules and entity type definitions, not hardcoded entity names — it would work on documents it has never seen",
            "format_compliance": "Output is valid JSON with name and type fields",
        },
        primary="coverage",
        iterations=iterations,
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
        generator_model=settings.classification_model,
        judge_model=settings.classification_model,
        clerk_model=settings.classification_model,
        evaluator=(
            f"uv run python {shlex.quote(str(evaluator_script))}"
            f" --candidate {{candidate_path}}"
            f" --samples-dir {shlex.quote(str(sample_dir))}"
            f" --golden-set {shlex.quote(str(golden_set_path))}"
            f" --output-dir {{output_dir}}"
            f" --iteration {{iteration}}"
        ),
        background=(
            f"This spec will be executed by Haiku to extract entities from documents.\n"
            f"Golden set: {golden_best[:2000]}\n\n"
            f"IMPORTANT: Each iteration, the evaluator runs the candidate spec against sample docs using Haiku.\n"
            f"Raw extraction results are written to eval-N/ directories in the output directory.\n"
            f"READ the raw extraction JSON files — don't just trust the quantitative summary.\n"
            f"Look for near-misses, type mismatches, and systematic patterns the metrics miss."
        ),
        on_iteration=_make_iteration_recorder(job_id, "extraction_spec", db_path, str(specs_dir / "general_spec")),
        **provider_kwargs,
    )

    # Store spec
    conn = get_connection(db_path)
    spec_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO specs (id, domain_path, version, spec_content, golden_set, score) VALUES (?, NULL, 1, ?, ?, ?)",
        (spec_id, spec_result.best_candidate, golden_best, spec_result.composite),
    )

    # Queue batch extraction
    batch_job_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO jobs (id, type, target, status, config) VALUES (?, 'extract_batch', 'general', 'queued', ?)",
        (batch_job_id, json.dumps({"spec_id": spec_id, "scope": "all_classified"})),
    )
    conn.commit()
    conn.close()

