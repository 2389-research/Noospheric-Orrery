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


# Base taxonomy mirrors the built-in general spec (orchestrator/specs/general_text.md) —
# 11 lowercase types — so simmered specs share one vocabulary with the out-of-box extractor.
# Domain simmering LAYERS domain-specific types on top of this (see _discover_domain_types).
BASE_TAXONOMY = """- person — named individuals (speakers, authors, founders, attendees)
- organization — companies, funds, institutions, teams, departments, brands
- topic — a field or subject area you could take a class in
- concept — a specific idea, theory, principle, or technique within a field
- technology — infrastructure, languages, protocols, frameworks, standards
- product — named commercial offerings (something you buy, subscribe to, or download)
- event — named events, meetings, milestones, releases
- location — places, regions, cities, venues
- document — referenced works, papers, books, articles
- date_ref — specific dates or time periods
- metric — named measurements, KPIs, or benchmarks with values"""

# Comma-joined base type names — passed as an EXCLUSION list to domain extraction (those
# types are already extracted by the general pass; domain refinement is additive).
BASE_TYPE_NAMES = ", ".join(ln.split("—")[0].strip(" -") for ln in BASE_TAXONOMY.splitlines())

GOLDEN_MAP_PROMPT = """You are an entity extraction system. Extract every entity from the text below that matches the type taxonomy.

Entity type taxonomy (extract ONLY these types):
{tax}
{exclude}
TEXT:
{chunk}

Rules:
- Extract only entities explicitly present in THIS text — do not invent.
- Extract ONLY entities whose type is in the taxonomy above; ignore everything else.
- Normalize names: lowercase, strip whitespace.
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


DOMAIN_TYPES_PROMPT = """The text below is from the '{domain}' domain of a knowledge graph.

The generic types below are ALREADY extracted by a separate general pass — do NOT propose these:
{base}

Entities already extracted in this domain (typed with the generic types — the granular detail
the domain types should newly capture is hiding inside these and in the text):
{existing}

The point of domain refinement is to capture MORE GRANULAR, domain-specific entities the generic
types miss or lump together. Propose 2-6 ADDITIONAL entity types specific to this domain. Prefer
types whose instances are CONCRETE and NAMED (a small extractor applies those reliably). For EACH,
give a concrete example taken from the entities/text above so the extractor knows what to look for.

SAMPLE TEXT:
{samples}

Return ONLY new domain-specific types, lowercase snake_case, one per line, EXACTLY as:
- type_name — one-line definition (e.g., "a concrete example from this domain")
If none are clearly warranted, return nothing."""


async def _discover_domain_types(sample_chunks, domain_path: str, settings, db_path: str = None) -> str:
    """Propose domain-specific entity types (beyond BASE_TAXONOMY) — the point of domain
    refinement. Grounded in the entities ALREADY extracted for this domain (so proposals fit
    the real data) and asks for a concrete example per type (so the extractor applies it).
    Returns extra taxonomy lines to append, or '' if none."""
    relay = Relay.from_settings(settings)
    model = settings.classification_model
    samples = "\n\n".join(str(c[1])[:1200] for c in sample_chunks[:6])

    # Ground in entities already extracted for this domain (by the general pass at ingest)
    existing = "(none yet)"
    if db_path:
        # Exact domain_path match is intentional: each domain node grounds discovery on its OWN
        # entities; child subdomains get their own discovery (per-node-stable-types model).
        conn = None
        try:
            conn = get_connection(db_path)
            rows = conn.execute(
                "SELECT DISTINCT e.canonical_name, e.type FROM entities e "
                "JOIN entity_sources es ON e.id = es.entity_id "
                "JOIN document_domains dd ON es.document_id = dd.document_id "
                "WHERE dd.domain_path = ? LIMIT 60",
                (domain_path,),
            ).fetchall()
            if rows:
                existing = "\n".join(f"- {r[0]} ({r[1]})" for r in rows)
        except Exception:
            pass
        finally:
            if conn is not None:
                conn.close()

    base_names = {ln.split("—")[0].strip(" -").lower() for ln in BASE_TAXONOMY.splitlines()}
    try:
        resp = await relay.complete(
            model=model, max_tokens=1024,
            messages=[{"role": "user", "content": DOMAIN_TYPES_PROMPT.format(
                domain=domain_path, base=BASE_TAXONOMY, existing=existing, samples=samples)}],
        )
        kept = []
        for ln in resp.text.splitlines():
            ln = ln.strip()
            if ln.startswith("-") and "—" in ln:
                name = ln.split("—")[0].strip(" -").lower()
                if name and name not in base_names:
                    kept.append(f"- {name} — {ln.split('—', 1)[1].strip()}")
        return "\n".join(kept)
    except Exception as e:
        print(f"  [domain_types] discovery failed: {e}", flush=True)
        return ""


async def _build_golden_set_mapreduce(sample_chunks, settings, job_id: str, db_path: str, taxonomy: str = None, exclude_types: str = "") -> str:
    """Decomposed golden-set generation for local models.

    MAP: one small extraction call per chunk (no tools, no agentic loop), extracting ONLY the
    types in `taxonomy`. For domain refinement, taxonomy = the domain-specific types only and
    `exclude_types` = the base type names (already extracted by the general pass) — so the
    domain golden is ADDITIVE (just the granular domain entities), not a re-extraction.
    Exact-(name,type) dedup across chunks only. NO canonicalization here — variant merging and
    type reconciliation are the normalization step's job on the live graph (issue #26).

    Replaces the agentic refine() generator, which stalls on local models (gemma4:26b loops
    on the read tool → empty candidate). Deterministic.
    """
    taxonomy = taxonomy or BASE_TAXONOMY
    exclude = (f"\nALREADY EXTRACTED by a separate pass — do NOT extract entities of these types: "
               f"{exclude_types}\n") if exclude_types else ""
    relay = Relay.from_settings(settings)
    extract_model = settings.extraction_model       # e4b — fast, purpose-built per-chunk extraction
    merged: dict[tuple, dict] = {}
    per_chunk = []
    for chunk in sample_chunks:
        text = chunk[1]  # (id, text, title)
        try:
            result = await relay.complete_structured(
                model=extract_model, max_tokens=2048,
                messages=[{"role": "user", "content": GOLDEN_MAP_PROMPT.format(tax=taxonomy, exclude=exclude, chunk=text)}],
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
            etype = str(e.get("type", "")).strip().lower()   # lowercase to match the taxonomy
            if name and (name, etype) not in merged:
                merged[(name, etype)] = {"name": name, "type": etype}

    golden = sorted(merged.values(), key=lambda e: (e["type"], e["name"]))
    types_seen = sorted({e["type"] for e in golden})
    print(f"  [golden_set] map: {len(golden)} entities from {len(sample_chunks)} chunks "
          f"(per-chunk: {per_chunk}); types: {types_seen}", flush=True)

    md = "\n".join([
        "# Golden Set\n",
        "## Entity Type Taxonomy",
        taxonomy,
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
             f"map extraction: {len(golden)} entities, {len(types_seen)} types (dedup/canonicalization deferred to normalization)",
             None, "map", False, None),
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


# --- Phase 2: decomposed rules-spec generation (shared by general + domain simmers) ---

SPEC_SEED_TEMPLATE = """# Entity Extraction Specification

## Task
Extract ALL entities from the document that match the type definitions below.
Output JSON objects with "name" (lowercase, trimmed) and "type" fields.

## Entity Type Definitions
{type_defs}

## Rules
### INCLUDE Rules
(refined from evaluation feedback)
### EXCLUDE Rules
(refined from evaluation feedback)

## Instructions
1. Read the whole document.
2. Extract every entity matching a type above. The type definitions are general — apply them
   to ANY document, not just this one. Do NOT hardcode specific names.
3. Normalize names (lowercase, trim); use the lowercase type names exactly as defined above.

Return ONLY a JSON array: [{{"name": "...", "type": "<one of the types above>"}}]"""

SPEC_EXTRACT_PROMPT = """You are an entity extraction system. Follow this spec exactly.

SPEC:
{spec}

TEXT:
{chunk}

Extract all entities present in the text according to the spec."""

SPEC_REVISE_PROMPT = """You are refining a GENERALIZED entity-extraction SPEC (a reusable prompt that must work on documents it has never seen). You are NOT extracting entities and you MUST NOT list specific entity names in the spec.{domain_note}

Current spec:
---
{spec}
---

When run on sample documents and compared to the ground-truth answer key:

MISSED (the spec should have extracted these but didn't — coverage gaps):
{misses}

WRONGLY EXTRACTED (noise / not real entities — precision errors):
{fps}

Rewrite the spec's INCLUDE/EXCLUDE rules so a model following it would catch the MISSED items
and avoid the WRONGLY-EXTRACTED ones — GENERALLY, by describing the PATTERN, not by naming
entities (e.g. "EXCLUDE vague descriptors like 'quality'", "INCLUDE single-word domain fields",
"extract multi-word names whole, not fragments"). Keep the type definitions and a few
ILLUSTRATIVE examples, but the body must be RULES, never a list of the answer-key entities.

Return the full revised spec (markdown). No commentary."""


def _parse_golden_keys(golden_md: str) -> set:
    import re
    m = re.search(r"\[.*\]", golden_md, re.DOTALL)
    if not m:
        return set()
    try:
        arr = json.loads(m.group())
    except Exception:
        return set()
    return {(str(e.get("name", "")).lower().strip(), str(e.get("type", "")).strip().lower())
            for e in arr if isinstance(e, dict) and e.get("name")}


def _strip_fences(text: str) -> str:
    import re
    t = text.strip()
    t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
    t = re.sub(r"\n?```$", "", t)
    return t.strip()


async def _refine_spec_rules(golden_md, sample_chunks, settings, job_id, db_path, iterations, domain_path=None, taxonomy=None):
    """DECOMPOSED Phase 2: produce a GENERALIZED rules spec (type defs + INCLUDE/EXCLUDE
    rules + illustrative examples), NOT a relisting of golden entities.

    Seeded from `taxonomy` (BASE_TAXONOMY, or base + domain-specific types) so the spec
    defines and extracts the domain's types. Deterministic F1 scoring against the golden
    (no LLM judge); the LLM only revises the rules from concrete misses/false-positives.
    Single-shot extraction per chunk (no agentic loop). Replaces the agentic refine(), which
    emitted hardcoded entity lists on local models.
    """
    taxonomy = taxonomy or BASE_TAXONOMY
    relay = Relay.from_settings(settings)
    extract_model = settings.extraction_model
    reviser_model = settings.classification_model
    golden = _parse_golden_keys(golden_md)
    domain_note = f" The spec targets the '{domain_path}' domain — keep its domain-specific types." if domain_path else ""

    spec = SPEC_SEED_TEMPLATE.format(type_defs=taxonomy)
    best = (-1.0, spec)
    prev_f1 = None
    for i in range(iterations + 1):  # iteration 0 scores the seed template
        extracted: set = set()
        for chunk in sample_chunks:
            try:
                res = await relay.complete_structured(
                    model=extract_model, max_tokens=2048,
                    messages=[{"role": "user", "content": SPEC_EXTRACT_PROMPT.format(spec=spec, chunk=chunk[1])}],
                    schema=GOLDEN_MAP_SCHEMA, tool_name="extract_entities",
                    tool_description="Extract entities from the text per the spec",
                )
                for e in (res.get("entities", []) if isinstance(res, dict) else []):
                    name = str(e.get("name", "")).lower().strip()
                    etype = str(e.get("type", "")).strip().lower()
                    if name:
                        extracted.add((name, etype))
            except Exception as ex:
                print(f"  [extraction_spec] extract error: {ex}", flush=True)

        hits = extracted & golden
        prec = len(hits) / len(extracted) if extracted else 0.0
        rec = len(hits) / len(golden) if golden else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        misses, fps = golden - extracted, extracted - golden
        regressed = prev_f1 is not None and f1 < prev_f1

        conn = get_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO simmer_iterations (id, job_id, phase, iteration, scores, composite, key_change, asi, judge_mode, regressed, candidate_preview) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), job_id, "extraction_spec", i,
                 json.dumps({"precision": round(prec, 2), "recall": round(rec, 2), "f1": round(f1, 2)}),
                 round(f1 * 10, 1),
                 ("seed rules template" if i == 0 else f"revised rules (P={prec:.2f} R={rec:.2f})"),
                 None, "rules-loop", regressed, None),
            )
            conn.commit()
        finally:
            conn.close()
        print(f"  [extraction_spec] iter {i}: F1={f1:.2f} P={prec:.2f} R={rec:.2f} "
              f"(ext={len(extracted)} miss={len(misses)} fp={len(fps)})", flush=True)

        if f1 > best[0]:
            best = (f1, spec)
        prev_f1 = f1

        if i < iterations:
            miss_s = ", ".join(f"{n} ({t})" for n, t in sorted(misses))[:1500] or "(none)"
            fp_s = ", ".join(f"{n} ({t})" for n, t in sorted(fps))[:1500] or "(none)"
            try:
                resp = await relay.complete(
                    model=reviser_model, max_tokens=4096,
                    messages=[{"role": "user", "content": SPEC_REVISE_PROMPT.format(
                        domain_note=domain_note, spec=spec, misses=miss_s, fps=fp_s)}],
                )
                revised = _strip_fences(resp.text)
                if revised:
                    spec = revised
            except Exception as ex:
                print(f"  [extraction_spec] revise error: {ex}", flush=True)
                break

    return best[1], round(best[0] * 10, 1)


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

    # Phase 2: DECOMPOSED rules-spec generation. Produces a GENERALIZED rules spec (type defs
    # + INCLUDE/EXCLUDE), scored deterministically by F1 against the golden — no agentic
    # generator (which relisted golden entities on local models) and no LLM judge.
    print(f"Refining extraction-spec rules ({len(sample_chunks)} chunks, job {job_id})", flush=True)
    spec_content, spec_score = await _refine_spec_rules(
        golden_best, sample_chunks, settings, job_id, db_path, iterations,
    )

    # Store spec
    conn = get_connection(db_path)
    spec_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO specs (id, domain_path, version, spec_content, golden_set, score) VALUES (?, NULL, 1, ?, ?, ?)",
        (spec_id, spec_content, golden_best, spec_score),
    )

    # Queue batch extraction
    batch_job_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO jobs (id, type, target, status, config) VALUES (?, 'extract_batch', 'general', 'queued', ?)",
        (batch_job_id, json.dumps({"spec_id": spec_id, "scope": "all_classified"})),
    )
    conn.commit()
    conn.close()

