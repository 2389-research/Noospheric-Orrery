# CLAUDE.md — Noospheric Orrery

Instructions for AI agents (Claude Code, etc.) working on this codebase.

## What This Project Is

An adaptive knowledge graph pipeline. Documents go in → the system classifies them into domains, simmers extraction specs via iterative LLM refinement, extracts entities, normalizes them, and visualizes the result as an interactive galaxy map.

Three services: orchestrator (FastAPI REST API), worker (background job processor), frontend (Next.js).

## Project Structure

```
orchestrator/
  src/
    main.py          — FastAPI app, CORS, router registration
    config.py        — Settings from env vars (AWS keys, model IDs, thresholds)
    db.py            — SQLite schema (init_db) + get_connection (WAL mode)
    models.py        — Pydantic request/response models
    routes/          — One file per route group
      ingest.py      — POST /ingest, POST /ingest/directory (the main pipeline entry point)
      documents.py   — GET /documents, GET /documents/{id}
      reader.py      — GET /documents/{id}/reader (entity spans for highlighted view)
      domains.py     — GET /domains
      entities.py    — GET /entities, GET /entities/{id}, GET /entities/{id}/cooccurrences
      jobs.py        — GET /jobs, GET /jobs/{id}/iterations
      simmer.py      — POST /simmer/general, POST /simmer/{domain_path}
      stats.py       — GET /stats
      normalize.py   — POST /normalize, GET /normalize/summary, GET /normalize/review
      subdomains.py  — POST /discover-subdomains
      graph.py       — GET /graph (cosmic_data_v4 format for the viz iframe)
    pipeline/        — Pure functions, no FastAPI coupling
      chunker.py     — Split document into fixed-size chunks
      excerpt.py     — Build adaptive excerpt for classification
      classifier.py  — Call Sonnet to classify document into domains
      domain_normalizer.py — Assign/normalize domains after classification
      extractor.py   — Call Haiku with a spec to extract entities from chunks
      normalizer.py  — Per-entity normalization (merge_map check → insert)
      embedding_normalizer.py — Batch normalization (embed → cluster → LLM review)
      cooccurrence.py — Compute co-occurrence edges from chunk→entity map
      subdomain_discovery.py — Find subdomains from extracted content

worker/
  src/
    main.py          — Poll loop: picks jobs every 5s, dispatches to handlers
    config.py        — Same env vars as orchestrator
    db.py            — Shared schema (identical to orchestrator/src/db.py)
    normalizer.py    — Entity normalization used during batch extraction
    jobs/
      runner.py      — pick_next_job, mark_job_running/completed/failed
      simmer_general.py — Run golden set + extraction spec simmering for general spec
      simmer_domain.py  — Same but for a specific domain
      extract_batch.py  — Run a spec against all docs in scope

frontend/
  src/
    app/             — Next.js App Router pages
      page.tsx       — /  (upload page)
      pipeline/      — /pipeline
      entities/      — /entities
      viz/           — /viz (iframe + postMessage cosmic viz)
      simmer/[id]/   — /simmer/{id} (simmer job detail)
      extraction/[id]/ — /extraction/{id} (batch extraction detail)
    components/      — Shared UI components
    lib/
      api.ts         — All fetch calls to the orchestrator
      types.ts       — TypeScript types
  public/
    cosmic-viz.html  — Self-contained Canvas2D galaxy visualization (DO NOT split into modules)
```

## Data Lives Outside the Repo

All persistent data is at `~/orrery-data/`:
- `~/orrery-data/orrery.db` — SQLite database
- `~/orrery-data/documents/` — uploaded file copies
- `~/orrery-data/specs/` — simmered spec files

In Docker, this maps to the `orrery-data` volume mounted at `/data`.

## Starting the Services

### Local Mode (SQLite, no cloud dependencies)

```bash
# Docker (recommended):
docker compose up

# Requires: .env file with LLM credentials (ANTHROPIC_BACKEND, AWS_ACCESS_KEY, etc.)
# Data persists at ./data/ on the host filesystem
# Ports: orchestrator → 8100, frontend → 3100
# Auth: noop (no sign-in required)
# Workspaces: multi-workspace via separate SQLite files
```

### Without Docker (native dev)

```bash
# Orchestrator
cd orchestrator && pip install -e . && uvicorn src.main:app --reload --port 8000

# Worker (separate terminal)
source /tmp/run-orchestrator.sh
cd worker && python -m src.main

# Frontend (separate terminal)
cd frontend && NEXT_PUBLIC_AUTH_MODE=noop BACKEND_URL=http://localhost:8000 npm run dev
```

The frontend uses `BACKEND_URL` for the Next.js API rewrite proxy. In Docker, it's set to the orchestrator service URL.

## Key Patterns

### All Claude API Calls Go Through orrery-relay

Never instantiate Anthropic clients directly. Always use the `Relay` class from `orrery-relay`:

```python
from orrery_relay import Relay

relay = Relay.from_settings(settings)
response = await relay.complete(
    model="claude-sonnet-4-6",
    messages=[{"role": "user", "content": "..."}],
    max_tokens=1024,
)
text = response.text
```

The relay supports three backends controlled by `ANTHROPIC_BACKEND` env var:
- `gateway` (default): Direct Anthropic API or proxy at `GATEWAY_URL`
- `bedrock`: AWS Bedrock with `AWS_ACCESS_KEY`/`AWS_SECRET_KEY`
- `ollama`: Local models via Ollama at `OLLAMA_URL` (default `http://localhost:11434`)

The `orrery-relay` package lives at `packages/orrery-relay/` and is a dependency of both orchestrator and worker via `[tool.uv.sources]` path reference.

### Model Names

Use friendly model names everywhere in config and code:
```text
# Cloud (Bedrock/Gateway)
claude-sonnet-4-6
claude-haiku-4-5
claude-opus-4-6

# Local (Ollama) — set CLASSIFICATION_MODEL and EXTRACTION_MODEL in .env
gemma4:26b      # classification, judging, generation (MoE, 4B active)
gemma4:e4b      # extraction, clerk (8B dense, good at structured output)
```

The relay handles translation to Bedrock inference profile IDs when running in bedrock mode. For ollama, model names are passed through as-is. Check `packages/orrery-relay/src/orrery_relay/backends.py` for the current mapping.

### Two Deployment Tiers

| Tier | Backend | Models | Embeddings |
|------|---------|--------|------------|
| Local with API | `bedrock` or `gateway` | Sonnet/Haiku | sentence-transformers |
| Fully local | `ollama` | gemma4:26b/e4b | sentence-transformers |

Auth is always noop (no sign-in required). Data is stored in SQLite.

Simmer jobs read `CLASSIFICATION_MODEL` for judge/generator and `EXTRACTION_MODEL` for clerk/extraction. All model references come from config — no hardcoded model names in the pipeline code.

### ⚠️ Simmer pipeline — READ THE THEORY BEFORE TOUCHING IT

The golden-set and extraction-spec refinement is a **simmer loop** — an RL-style iterative
refinement process. Its stages (**generate → evaluate → judge → reflect**, driven by an **ASI** =
the single highest-leverage fix) are **NOT incidental structure**. Each stage prevents a specific,
documented failure. Agents repeatedly try to "simplify" this by collapsing stages without
understanding why they exist — and reintroduce the exact failures the design prevents. **Do not.**

**Read before modifying / removing / merging / "simplifying" any stage:**
- Blog (the *why*, with a worked example of score inflation): https://2389.ai/posts/simmer-skill/
- simmer-sdk repo: https://github.com/2389-research/simmer-sdk
- simmer-sdk README: `simmer-sdk/README.md`
- Canonical process spec: `simmer-sdk/docs/spec.md`
- Local-model decomposition guide: `simmer-sdk/docs/local-models-guide.md`
- Judge definition (what an ASI is, scoring, calibration): `simmer-sdk/src/simmer_sdk/skill_reference/judge.md`
  — our judge **loads this skill at runtime** via `build_judge_prompt`, so it is the live contract, not just docs.

**Invariants this implementation MUST preserve** (enforced by `worker/tests/test_simmer_core.py`):
1. The **judge** is a stage distinct from the generator — never merge them. (Merging them was the #27 regression.)
2. **Context discipline:** the generator is steered by the **ASI only** — never the raw scores or evaluator output.
3. The judge is **calibrated** against the iteration-0 seed + its scores (without it, scores inflate while quality stagnates).
4. The **evaluator (F1) FEEDS the judge**, it does not replace it.
5. The judge prompt is built from the simmer-sdk **judge skill** (`build_judge_prompt`), NOT a hand-rolled bare prompt (a bare prompt drops the ASI definition → empty/garbage ASIs).
6. **Reflect** is kept: best-so-far + regression tracking; every iteration recorded to `simmer_iterations`.

**Orrery's adaptation (why this differs from stock simmer-sdk — do not "fix" it back):** simmer-sdk's
`refine()` runs these stages as **agentic `ClaudeSDKClient` loops**. Local models (gemma4) stall in
agentic loops, so orrery runs every stage as a **bounded, non-agentic relay call**
(`worker/src/jobs/simmer_core.py`: `simmer_loop` + `relay_judge`), with `think:false` (reasoning
models otherwise emit only thinking and empty the answer). Re-agentifying these stages "to match the
SDK" reintroduces the stalls.

**Case study — #27:** a "decomposition" PR deleted the judge entirely (golden phase became a bare map
with no evaluation). Recovery required re-deriving the whole process from the spec + judge skill
(commits `9829613..a9037e0`). If you're removing a stage to "simplify," you are likely repeating #27.

### simmer-sdk dependency

The worker does **not** call `refine()` (the agentic loop). It runs the decomposed loop in
`worker/src/jobs/simmer_core.py` and reuses simmer-sdk only for the **judge contract** —
`build_judge_prompt` (loads the judge skill) and `parse_judge_output`. simmer-sdk is an internal dependency:
- **Repo**: `https://github.com/2389-research/simmer-sdk`
- **Docker**: clone alongside, then `cp -r simmer-sdk/ worker/simmer-sdk/` before `docker compose build`
- **Local dev**: `git clone https://github.com/2389-research/simmer-sdk.git && pip install -e simmer-sdk/`

### SQLite WAL Mode

Both orchestrator and worker write concurrently. Every connection opens with:
```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")
```

This is handled by `get_connection()` in `db.py` — always use that, never open SQLite directly.

### Domain Spec Cascade

When a document is ingested, the pipeline walks up the domain tree and applies every spec that exists at any ancestor level. A doc in `business/product_development/strategy` gets the `strategy` spec, then the `product_development` spec, then the `business` spec (deepest first). This is in `ingest.py` under the "cascade through domain specs" comment.

### Entity Normalization

Normalization happens at two levels:
1. **Per-entity** (inline during ingest): `normalize_entity()` checks merge_map, inserts if new, returns canonical entity_id
2. **Batch** (via `POST /normalize`): embedding similarity clustering + LLM review for ambiguous pairs

The `normalization_review_queue` table holds pairs the system is uncertain about. Use `GET /normalize/review` + `POST /normalize/review/{id}` to resolve them.

### Graph Corrections (self-healing loop) — see `docs/graph-corrections.md`

Agents consuming the graph can propose corrections (`propose_correction` MCP write tool → `graph_issues`); an advisory model **judge** annotates each; a human approves/rejects in the `CorrectionsPanel`; approval **reversibly** edits the graph. **`docs/graph-corrections.md` is the canonical reference for how each action (invalidate · retype · rename · merge; split unbuilt) applies AND reverses — read/update it when touching this code.** Key invariants:
- **Reversible soft-delete, never hard-delete** on the corrections path. Active graph = `WHERE invalid_at IS NULL` (threaded through graph/entities/traversal reads; NOT yet search). Every apply writes an append-only `normalization_log` row (history + undo + model-vs-human calibration data).
- **Judge is advisory, human-gated** — it orders the queue, never auto-applies. Bounded non-agentic relay call (`think:false`), source-grounded, no web search. Periodic sweep (`JUDGE_SWEEP_INTERVAL_SECONDS`, default 900) + manual `POST /corrections/judge`.
- **Merge** recomputes the survivor's 1-hop co-occurrence edges (weights must combine, not double-count) and soft-deletes the loser — do NOT replace it with the naive redirect in `embedding_normalizer` (that double-counts + hard-deletes). `rollback_merge` uses the log's snapshot; undo across overlapping neighborhoods is LIFO (see the doc's ordering constraint).
- Dedup lookups (`get`/`get_by_name`) pass `include_invalid=True` so re-ingest re-attaches to an invalidated node instead of resurrecting it as a duplicate.

### Cosmic Viz is a Self-Contained HTML File

`frontend/public/cosmic-viz.html` is a single-file Canvas2D app. It communicates with the Next.js shell via `postMessage`:
- Viz → Shell: `{ type: "node_selected", nodeType, data }` when user clicks a node
- Viz → Shell: `{ type: "node_cleared" }` when user deselects
- Shell → Viz: `{ type: "panel_closed" }` when user closes the side panel

Do not try to decompose it into React components. The iframe boundary is intentional.

The viz fetches `GET /graph` from the orchestrator for data (via `NEXT_PUBLIC_API_URL` stored in a meta tag or window variable).

## CORS

The orchestrator has `allow_origins=["*"]` in development. If you tighten this, the frontend iframe and direct API calls from the viz HTML will break.

## Testing

**Orchestrator:** 11 test files, 45+ tests
```bash
cd orchestrator && pytest tests/ -v
```

**Worker:** 2 test files, 7+ tests
```bash
cd worker && pytest tests/ -v
```

Tests use `tmp_path` fixtures for SQLite isolation: the orchestrator `conftest.py` gives each test a test client plus a fresh **file-backed** DB at `tmp_path/test.db`.

**Do not "fix" this to `:memory:`** — it cannot work here, for two reasons:
- `":memory:"` is **per-connection**. `SQLiteDataStore(db_path)` calls `init_db(db_path)` and then `get_connection(db_path)`, so the schema and the store would land in two *separate* empty databases.
- **WAL is unavailable in memory.** `PRAGMA journal_mode=WAL` on `:memory:` silently returns `memory`, so the tests would stop exercising the journal mode this codebase depends on for concurrent orchestrator/worker writes.

`tmp_path` is already per-test, so the fixture is fresh either way.

## Common Gotchas

- **`birthScale` in the viz**: entities get a `birthScale` CSS property for their entrance animation. If you add new entity fields, make sure the viz ignores unknown properties gracefully.
- **CORS in viz iframe**: the `cosmic-viz.html` fetches the graph endpoint directly. If the orchestrator URL changes, update the meta tag / env var that the viz reads.
- **Bedrock model IDs**: always include the `us.` prefix and the `-v1:0` suffix. The exact string matters — Bedrock rejects anything that doesn't match a registered inference profile.
- **WAL mode required**: if you add a new SQLite connection anywhere, add the PRAGMA statements. Forgetting causes `database is locked` errors under load.
- **Domain path format**: paths use `/` as separator (e.g., `techniques/wet-blending`). Treat as a hierarchical key, not a filesystem path. The `LIKE ? || '%'` pattern in queries does prefix matching.
- **`job_id` on entity_sources**: the `entity_sources` table has a `job_id` column added after initial design. The `/entities?job_id=` filter scopes the entity list to entities extracted by a specific job — useful for the extraction detail page.
