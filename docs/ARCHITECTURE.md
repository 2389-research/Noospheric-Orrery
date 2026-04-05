# Noospheric Orrery — Architecture Reference

**Date:** 2026-03-27

Deep reference for anyone making structural changes to the system.

## System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│  User (browser)                                                 │
│    http://localhost:3100                                        │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│  frontend  (Next.js, port 3100 in Docker / 3000 in dev)        │
│                                                                 │
│  /           Upload page (file-upload component)               │
│  /pipeline   Job list + domain taxonomy tree                   │
│  /entities   Paginated entity table with filters               │
│  /viz        cosmic-viz.html iframe + GalaxyPanel overlay      │
│  /simmer/[id]     Simmer iteration detail                      │
│  /extraction/[id] Batch extraction detail + reader             │
│                                                                 │
│  All API calls → NEXT_PUBLIC_API_URL (orchestrator)            │
└──────────────────────────────┬──────────────────────────────────┘
                               │ HTTP REST
┌──────────────────────────────▼──────────────────────────────────┐
│  orchestrator  (FastAPI, port 8100 in Docker / 8000 in dev)    │
│                                                                 │
│  Handles ingest, classification, synchronous extraction        │
│  Queues async jobs for the worker                              │
│  Serves graph data for cosmic viz                              │
└──────┬───────────────────────────────────────────────┬──────────┘
       │ SQLite WAL (shared volume)                    │ AWS Bedrock
┌──────▼────────────────────────────┐     ┌─────────────▼──────────┐
│  ~/.local/share/orrery/orrery.db  │     │  claude-sonnet-4       │
│  ~/.local/share/orrery/documents/ │     │  claude-haiku-4        │
│  ~/.local/share/orrery/specs/     │     │  (cross-region profiles)│
└──────▲────────────────────────────┘     └────────────────────────┘
       │ SQLite WAL (same volume)
┌──────┴──────────────────────────────────────────────────────────┐
│  worker  (Python asyncio, no HTTP port)                        │
│                                                                 │
│  Polls jobs table every 5s                                     │
│  simmer_general  → golden set + general extraction spec        │
│  simmer_domain   → golden set + domain extraction spec         │
│  extract_batch   → run spec against all target documents       │
│                                                                 │
│  Uses simmer-sdk for iterative refinement loops                │
└─────────────────────────────────────────────────────────────────┘
```

## Pipeline Stages with Data Flow

### Stage 1 — Ingest and Store

**Trigger:** `POST /ingest` (file) or `POST /ingest/directory`

**Actions:**
1. SHA-256 content hash dedup — skip if document already exists
2. Store in `documents` table (status: `pending`)
3. Chunk document into fixed-size pieces (default 2000 chars, no mid-word breaks)
4. Store all chunks in `chunks` table with `chunk_index` and `offset`

**Output:** `doc_id`, list of `chunk` objects (id, index, offset, length, text)

### Stage 2 — Domain Classification

**Trigger:** Immediately after store (synchronous, ~2-3s)

**Model:** `claude-sonnet-4` via Bedrock

**Input:**
- Adaptive excerpt: whole doc if < 6K chars; otherwise title + first 2K + middle 2K + last 2K chars
- Existing domain taxonomy (all paths from `domains` table)

**Output from Sonnet:**
- `primary_domain` — the main domain path
- `secondary_domains` — additional relevant paths
- `new_domain_proposals` — new paths not in the taxonomy

**Domain Normalization Cascade (inline):**
```
For each proposed domain label:
1. Check domain_merge_map — if seen before, use canonical path
2. Embed the label (all-MiniLM-L6-v2)
3. Compare cosine similarity to existing domain embeddings
4. similarity > 0.85 → merge into existing domain (auto)
5. 0.70–0.85 → flag for LLM review (Sonnet confirms merge or keep separate)
6. < 0.70 → insert as new domain
7. Update domain_merge_map with decision
```

**State changes:** `document_domains` rows inserted; `domains.document_count` incremented; document status → `classified`

### Stage 3 — General Extraction (if spec exists)

**Trigger:** Immediately after classification

**Model:** `claude-haiku-4` via Bedrock, with simmered general spec

**Process:**
```
For each chunk:
  → Send chunk text + extraction spec prompt to Haiku
  → Parse JSON response: [{name, type, chunk_id}]

Deduplicate within document
For each entity:
  → normalize_entity(conn, name, type)
     1. Check merge_map → use canonical if found
     2. If new: insert into entities table, return id
  → Insert entity_source (entity_id, doc_id, chunk_id, 'general', spec_version)
  → Track chunk → [entity_id, ...] map for co-occurrence

Compute co-occurrence edges:
  For each pair of entities in the same chunk:
    → Upsert relationship (from, to, type='co_occurs', weight=chunk_frequency)
```

**State changes:** `entities`, `entity_sources`, `relationships` rows inserted; document status → `extracted`

### Stage 4 — Domain Spec Cascade

**Trigger:** After general extraction, for each domain the document belongs to

**Process:**
```
For each domain_path in doc's domains:
  Walk up the tree: a/b/c → [a/b/c, a/b, a] (deepest first)
  For each ancestor_path:
    Find the latest spec WHERE domain_path = ancestor_path
    Skip if this spec_id was already run for this document
    Run extract_document() with domain spec
    Insert entity_sources with extraction_pass = 'domain-specific'
    Add to chunk→entity map for co-occurrence recompute

After all domain specs: recompute all co-occurrence edges
```

**State changes:** More `entity_sources` rows; document status → `enriched`

### Stage 5 — Threshold Checks and Job Queuing

**Trigger:** After all extraction steps

```
No general spec exists?
  → Queue simmer_general job (if not already queued/running)
  → This happens on the very first upload

Each domain this doc belongs to:
  document_count >= DOMAIN_SPEC_THRESHOLD AND no spec yet?
  → Queue simmer_domain job for that domain
```

### Stage 6 — Simmering (async, worker)

The worker picks up `simmer_general` and `simmer_domain` jobs.

**Phase 1 — Golden Set Simmering:**
```
Select ~10 representative documents from corpus (or domain)
Review existing entities on those docs (don't re-find obvious ones)
Send docs to Sonnet: "Build a comprehensive entity set for these docs"
Seed ontology: Person, Organization, Topic, Event, Location, Thing
                (domain specs start from general spec's types)

simmer-sdk refine() loop (default 5 iterations):
  Evaluator: score_golden_set.py --docs {candidate_path}
  Criteria:
    coverage — captures everything a domain expert would want
    precision — no noise or hallucinated entities
    taxonomy_quality — entity types are meaningful and consistent
  Primary criterion: coverage

Output: golden set JSON (entities + types + relationships)
Store in specs table (golden_set column)
```

**Phase 2 — Extraction Spec Simmering:**
```
Template a Haiku prompt from the golden set
  (entity types from golden set, examples, normalization hints)

simmer-sdk refine() loop (default 5 iterations):
  Evaluator: eval_runner_haiku.py runs spec against held-out docs
  Scorer: eval_scorer.py fuzzy-matches extracted vs golden set
  Criteria:
    coverage — recall against golden set entities
    precision — zero false positives
    format_compliance — valid JSON matching output contract
  Primary: coverage

Output: simmered extraction spec (the prompt text)
Store in specs table (spec_content column), version incremented
```

Each simmer iteration is recorded in `simmer_iterations` and `simmer_criterion_details`.

### Stage 7 — Batch Extraction (async, worker)

After simmering completes, a `extract_batch` job processes all target documents:

```
For each document in scope:
  Run extract_document() with the new spec
  normalize_entity() for each extracted entity
  Compute co-occurrence edges
  Insert entity_sources with spec_version
  Update document status → extracted or enriched
```

### Stage 8 — Visualization

`GET /graph` computes the `cosmic_data_v4` payload:

- **domain_positions** — domains laid out in a circle using branching-level detection + golden ratio subgroup placement
- **region_colors** — hierarchy-aware HSL colors (top-level domains divide the hue wheel equally; subdomains use golden ratio offsets within each slice; deeper domains desaturate)
- **entities** — all entities with `domainWeights` (which fraction of their source documents belong to each domain)
- **trade_routes** — domain pairs that share entities, weighted by shared entity mention count
- **videos** — 50 most recent documents for comet animations
- **active_simmers** — domains currently being simmered (for nebula "charging" animation)

## Database Schema

All tables are in a single SQLite file at `/data/orrery.db` (Docker) or `~/orrery-data/orrery.db` (local).

```sql
-- Uploaded documents
documents (
  id           TEXT PRIMARY KEY,   -- uuid
  title        TEXT,
  source_path  TEXT,               -- original file path
  content      TEXT,
  content_hash TEXT,               -- sha256, used for dedup
  metadata     TEXT,               -- JSON blob (author, channel, etc.)
  created_at   TIMESTAMP,
  status       TEXT                -- pending | classified | extracted | enriched
);
INDEX on content_hash

-- Fixed-size chunks of each document
chunks (
  id           TEXT PRIMARY KEY,
  document_id  TEXT REFERENCES documents(id),
  chunk_index  INTEGER,            -- order within document
  offset       INTEGER,            -- char offset in content
  length       INTEGER,
  text         TEXT
);

-- Hierarchical domain taxonomy
domains (
  id             TEXT PRIMARY KEY,
  path           TEXT UNIQUE,      -- e.g., "techniques/wet-blending"
  parent_path    TEXT,             -- nullable
  document_count INTEGER DEFAULT 0,
  spec_version   INTEGER,          -- null if no simmered spec yet
  created_at     TIMESTAMP
);

-- Normalization cache for domain labels
domain_merge_map (
  from_label TEXT PRIMARY KEY,
  to_path    TEXT REFERENCES domains(path)
);

-- Document-to-domain assignments (many-to-many)
document_domains (
  document_id TEXT REFERENCES documents(id),
  domain_path TEXT REFERENCES domains(path),
  is_primary  BOOLEAN,
  confidence  REAL,
  PRIMARY KEY (document_id, domain_path)
);

-- Canonical entities
entities (
  id             TEXT PRIMARY KEY,
  canonical_name TEXT,
  type           TEXT,             -- Person, Technique, Topic, etc.
  created_at     TIMESTAMP
);

-- Provenance: which doc/chunk/pass produced this entity
entity_sources (
  entity_id      TEXT REFERENCES entities(id),
  document_id    TEXT REFERENCES documents(id),
  chunk_id       TEXT REFERENCES chunks(id),
  extraction_pass TEXT,            -- 'general' | 'domain-specific'
  spec_version    INTEGER,
  job_id          TEXT REFERENCES jobs(id)
);

-- Entity normalization cache
merge_map (
  from_name    TEXT PRIMARY KEY,
  to_entity_id TEXT REFERENCES entities(id)
);

-- Co-occurrence and typed edges
relationships (
  id           TEXT PRIMARY KEY,
  from_entity  TEXT REFERENCES entities(id),
  to_entity    TEXT REFERENCES entities(id),
  type         TEXT,               -- 'co_occurs' | 'mentions'
  weight       REAL,               -- chunk frequency for co_occurs
  source_chunk TEXT REFERENCES chunks(id)
);

-- Pipeline jobs
jobs (
  id           TEXT PRIMARY KEY,
  type         TEXT,               -- simmer_general | simmer_domain | extract_batch
  target       TEXT,               -- domain path or "general"
  status       TEXT DEFAULT 'queued',  -- queued | running | completed | failed
  config       TEXT,               -- JSON blob
  result       TEXT,               -- JSON blob
  created_at   TIMESTAMP,
  started_at   TIMESTAMP,
  completed_at TIMESTAMP
);

-- Per-iteration simmer history
simmer_iterations (
  id              TEXT PRIMARY KEY,
  job_id          TEXT REFERENCES jobs(id),
  phase           TEXT,            -- 'golden_set' | 'extraction_spec'
  iteration       INTEGER,
  scores          TEXT,            -- JSON: {criterion: score}
  composite       REAL,
  key_change      TEXT,            -- what changed this iteration
  asi             TEXT,            -- area of suggested improvement
  judge_mode      TEXT,            -- 'single' | 'board'
  regressed       BOOLEAN,
  candidate_preview TEXT,
  created_at      TIMESTAMP
);
INDEX on job_id

-- Per-criterion details for each simmer iteration
simmer_criterion_details (
  id           TEXT PRIMARY KEY,
  iteration_id TEXT REFERENCES simmer_iterations(id),
  criterion    TEXT,
  score        INTEGER,
  seed_score   INTEGER,
  evidence     TEXT,
  improve      TEXT
);

-- Simmered specs (general and per-domain)
specs (
  id           TEXT PRIMARY KEY,
  domain_path  TEXT,               -- null = general spec
  version      INTEGER,
  spec_content TEXT,               -- the extraction prompt
  golden_set   TEXT,               -- JSON: the golden entity set
  score        REAL,               -- composite score from simmering
  created_at   TIMESTAMP
);

-- Cached entity embeddings (for normalization)
entity_embeddings (
  entity_id TEXT PRIMARY KEY REFERENCES entities(id),
  embedding BLOB                   -- float32 array serialized
);

-- Normalization audit log
normalization_log (
  id            TEXT PRIMARY KEY,
  from_entity_id TEXT,
  from_name      TEXT,
  to_entity_id   TEXT,
  to_name        TEXT,
  method         TEXT,             -- 'merge_map' | 'embed_auto' | 'llm_review'
  similarity     REAL,
  created_at     TIMESTAMP
);

-- Ambiguous pairs waiting for manual or LLM resolution
normalization_review_queue (
  id          TEXT PRIMARY KEY,
  entity_a_id TEXT,
  entity_a_name TEXT,
  entity_b_id TEXT,
  entity_b_name TEXT,
  similarity  REAL,
  status      TEXT DEFAULT 'pending',  -- pending | resolved
  resolution  TEXT,                    -- 'merge' | 'keep_separate'
  created_at  TIMESTAMP
);
```

## API Endpoint Reference

### Ingest

**`POST /ingest`** — Upload a single file

Request: `multipart/form-data` with `file` field (UTF-8 text)

Response:
```json
{
  "document_id": "uuid",
  "title": "filename",
  "domains": ["techniques/wet-blending"],
  "entity_count": 47,
  "jobs_queued": ["uuid"]
}
```

**`POST /ingest/directory`** — Ingest all text files from a local directory

Request:
```json
{ "path": "/absolute/path/to/directory" }
```

Response: `{ "documents": [...IngestResult], "total": 5 }`

Accepts: `.txt`, `.md`, `.json`, `.csv`

---

### Documents

**`GET /documents?limit=50&offset=0`**

Response: array of `{ id, title, status, created_at, domains: string[], entity_count }`

**`GET /documents/{document_id}`**

Response: `{ id, title, source_path, content, metadata, status, created_at, domains: [{path, is_primary, confidence}], entities: [{id, canonical_name, type}] }`

**`GET /documents/{document_id}/reader`**

Returns document segmented into text/entity spans for the highlighted reader view.

Response:
```json
{
  "document": { "id", "title", "status", "domains": [] },
  "entities": [{ "id", "canonical_name", "type", "source_count", "mention_count", "positions": [float], "snippets": [string] }],
  "segments": [{ "type": "text"|"entity", "text", "entity_id"?, "entity_name"?, "entity_type"?, "is_new"? }],
  "total_mentions": 123
}
```

---

### Domains

**`GET /domains`**

Returns all domains with `document_count > 0`, ordered by path.

Response: `[{ id, path, parent_path, document_count, spec_version, created_at }]`

`spec_version` is null if no spec has been simmered yet.

---

### Entities

**`GET /entities?limit=50&offset=0&type=Technique&domain=techniques&job_id=uuid`**

All parameters optional. `job_id` scopes to entities extracted by a specific job, with `is_new` flag indicating entities created during that job.

Response (default): `[{ id, canonical_name, type, source_count }]`
Response (with job_id): `[{ id, canonical_name, type, source_count, is_new: bool }]`

**`GET /entities/{entity_id}`**

Response:
```json
{
  "id": "uuid",
  "canonical_name": "wet-blending",
  "type": "Technique",
  "created_at": "...",
  "sources": [{ "document_id", "chunk_id", "extraction_pass", "spec_version", "job_id" }],
  "merge_history": ["wet blending", "wetblend"]
}
```

**`GET /entities/{entity_id}/cooccurrences?limit=10`**

Response: `[{ id, canonical_name, type, weight }]` — entities sharing chunks with this entity, sorted by co-occurrence weight.

---

### Jobs

**`GET /jobs?status=running`**

`status` filter optional. Returns all jobs descending by `created_at`.

Response: `[{ id, type, target, status, created_at, started_at, completed_at, results }]`

**`GET /jobs/{job_id}/iterations`**

Full simmer iteration history grouped by phase.

Response:
```json
{
  "job_id": "uuid",
  "job_type": "simmer_general",
  "target": "general",
  "status": "completed",
  "phases": {
    "golden_set": [{ "phase", "iteration", "scores", "composite", "key_change", "asi", "judge_mode", "regressed", "created_at", "criterion_details": [{ "criterion", "score", "seed_score", "evidence", "improve" }] }],
    "extraction_spec": [...]
  },
  "total_iterations": 10
}
```

---

### Simmer (manual triggers)

**`POST /simmer/general`**

Returns `409` if a general simmer is already queued or running.
Response: `{ "job_id": "uuid", "status": "queued" }`

**`POST /simmer/{domain_path}`**

`domain_path` must match an existing entry in `domains`. Returns `404` if not found, `409` if already running.
Response: `{ "job_id": "uuid", "status": "queued" }`

---

### Stats

**`GET /stats`**

Response: `{ "document_count", "entity_count", "domain_count", "active_jobs" }`

---

### Normalization

**`POST /normalize`**

Runs the full normalization cascade on all entities. Synchronous — may take several seconds on large corpora.

Response: `{ "merges": int, "reviewed": int, "queued_for_review": int }`

**`GET /normalize/summary`**

Response: `{ "merges_by_method": { "embed_auto": int, "llm_review": int }, "total_merges": int, "pending_reviews": int, "recent_merges": [{ "from", "to", "method", "similarity", "date" }] }`

**`GET /normalize/review`**

Response: array of pending `normalization_review_queue` items.

**`POST /normalize/review/{review_id}?action=merge`**

`action`: `merge` or `keep_separate`
Response: `{ "status": "resolved", "action": "merge" }`

---

### Subdomain Discovery

**`POST /discover-subdomains`**

Uses Sonnet to analyze extracted content and propose subdomain splits for domains that have grown large enough to warrant it. Results are inserted into the `domains` table.

---

### Graph

**`GET /graph`**

Returns `cosmic_data_v4` format consumed by `cosmic-viz.html`.

Response:
```json
{
  "domain_positions": { "domain/path": { "x": 0.5, "y": 0.3 } },
  "domain_video_counts": { "domain/path": 42 },
  "domain_specs": { "domain/path": { "spec_version": 2 } | null },
  "active_simmers": ["domain/path"],
  "region_colors": { "domain/path": "#4a90d9" },
  "subdomains": ["domain/path/sub"],
  "videos": [{ "id", "title", "domains": [], "primary" }],
  "entities": [{ "entityId", "name", "type", "videoCount", "domainWeights": { "domain/path": 0.7 } }],
  "v3_entities": [],
  "trade_routes": [{ "source": "domain/a", "target": "domain/b", "weight": 150 }]
}
```

---

### Health

**`GET /health`**

Response: `{ "status": "ok" }`

## Three-Tier Normalization Cascade

Both entity normalization and domain normalization follow the same three-tier pattern:

```
Tier 1 — String Rules (deterministic, free)
  lowercase
  strip leading/trailing whitespace
  collapse punctuation variants
  plural collapse (only when both forms exist in corpus)

Tier 2 — Embedding Similarity (scalable)
  Embed with all-MiniLM-L6-v2
  Agglomerative clustering (cosine distance)
  similarity > 0.85 → auto-merge (use highest-frequency member as canonical)
  similarity 0.70–0.85 → queue for LLM review

Tier 3 — LLM Review (accurate, expensive, only for ambiguous tail)
  Sonnet reviews each flagged pair
  "dark beige" ≠ "light beige" (similarity high but semantically distinct)
  "3d printer" ≠ "3d printing" (tool vs technique)
  Decision stored in merge_map (never re-evaluated)
```

**Canonical name selection:** the highest-frequency member of a merged cluster, not LLM-chosen. Ensures consistency across runs.

**Incremental normalization:** per-entity normalization (during ingest) checks merge_map first — O(1) lookup, no embedding needed for known names. Batch normalization (`POST /normalize`) finds new clusters from recently added entities.

## Domain Spec Cascade

Specs are additive and hierarchical:

```
Document in: business/product_development/strategy/ecommerce

Spec checks (deepest first):
  1. business/product_development/strategy/ecommerce spec (most specific)
  2. business/product_development/strategy spec
  3. business/product_development spec
  4. business spec

General spec always runs first (if exists).
Each spec adds entities on top — extraction passes are tagged separately.
```

This means:
- A general spec extracts Person, Topic, Organization, etc. across all domains
- A `business` spec adds Contract, Revenue, Milestone for all business docs
- A `product_development/strategy` spec adds Product, Roadmap, OKR for those specific docs

The `entity_sources.extraction_pass` field (`general` vs `domain-specific`) lets the frontend show which layer each entity came from.

## Subdomain Discovery Flow

`POST /discover-subdomains` runs `pipeline/subdomain_discovery.py`:

1. For each domain with enough documents, sample representative docs
2. Send to Sonnet with existing taxonomy: "What distinct sub-topics do you see?"
3. Parse proposed subdomain paths
4. Run domain normalization cascade on proposals
5. Insert new subdomains with `parent_path` set
6. Re-classify documents that should move to the more specific domain

This runs on-demand — not automatically triggered. Use it when a domain is growing large and taxonomy resolution is getting blurry.

## Cosmic Viz Architecture

The visualization lives in a single file: `frontend/public/cosmic-viz.html`.

**Rendering:**
- Canvas2D (not WebGL)
- 60fps animation loop via `requestAnimationFrame`
- Entity positions calculated from `domainWeights` — entities float between their weighted domain centroids

**Data loading:**
- On load, fetches `GET /graph` from `NEXT_PUBLIC_API_URL`
- Falls back to demo data if fetch fails

**Three nebula states per domain:**
- `default` — static glow at domain position
- `simmering` — animated pulse (domain is in `active_simmers` list)
- `complete` — brighter, larger glow (domain has a spec)

**postMessage bridge:**
The viz is embedded in an iframe inside `/viz/page.tsx`. Communication:

```
Viz → Shell (user interaction):
  { type: "node_selected", nodeType: "entity"|"domain"|"trade_route", data: {...} }
  { type: "node_cleared" }

Shell → Viz (UI events):
  { type: "panel_closed" }
```

**Galaxy Panel** (`components/galaxy/galaxy-panel.tsx`):
Three panel types based on `nodeType`:
- `entity` — canonical name, type, domain distribution donut chart, co-occurrence list
- `domain` — domain name, doc count, spec status, entity list
- `trade_route` — source/target domains, shared entity count, weight

## Configuration Reference

All settings are in `orchestrator/src/config.py` and `worker/src/config.py` (identical pattern):

| Env Var | Default | Description |
|---------|---------|-------------|
| `AWS_ACCESS_KEY` | required | Bedrock auth |
| `AWS_SECRET_KEY` | required | Bedrock auth |
| `AWS_REGION` | `us-east-1` | Bedrock region |
| `CLASSIFICATION_MODEL` | `us.anthropic.claude-sonnet-4-20250514-v1:0` | Must include `us.` prefix and `-v1:0` suffix |
| `EXTRACTION_MODEL` | `us.anthropic.claude-haiku-4-20250514-v1:0` | Same format requirement |
| `GENERAL_SPEC_THRESHOLD` | `10` | Docs before auto-simmering general spec |
| `DOMAIN_SPEC_THRESHOLD` | `20` | Docs in domain before auto-simmering domain spec |
| `SIMMER_ITERATIONS` | `5` | Refinement iterations per simmer phase |
| `CHUNK_SIZE` | `2000` | Characters per extraction chunk |
| `WORKER_POLL_INTERVAL` | `5` | Seconds between job queue polls |
| `DB_PATH` | `$XDG_DATA_HOME/orrery/orrery.db` | SQLite path |
| `DOCUMENTS_DIR` | `$XDG_DATA_HOME/orrery/documents` | Uploaded file copies |
| `SPECS_DIR` | `$XDG_DATA_HOME/orrery/specs` | Simmered spec files |

Local dev defaults to `~/.local/share/orrery/` (XDG). Docker overrides via `.env` to `/data/`. The env script at `/tmp/run-orchestrator.sh` sets credentials.
