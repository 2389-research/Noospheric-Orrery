# Orchestrator Service — Design Spec

**Date:** 2026-05-20
**Status:** Current implementation reference
**Purpose:** FastAPI orchestrator + simmer worker + Next.js dashboard to wire together the validated extraction pipeline

## Current State (as of 2026-05-20)

This section documents what has been built relative to what was originally planned. Updated at implementation time.

### Built and Shipped

- [x] **Three-container architecture** — orchestrator (FastAPI :8100), worker (asyncio poll loop), frontend (Next.js :3100) via `docker compose up`
- [x] **Full ingest pipeline** — upload text/image file or directory, classify through `orrery-relay`, extract with built-in or simmered general spec, cascade domain text specs, compute co-occurrence edges
- [x] **Domain normalization** — inline during classification; `domain_merge_map` lookup, exact path reuse, otherwise insert new domain with derived `parent_path`
- [x] **Entity normalization** — per-entity `merge_map` check at ingest time; batch cascade via `POST /normalize`; `normalization_review_queue` for manual resolution
- [x] **Built-in general specs** — `orchestrator/specs/general_text.md` and `general_image.md` keep cold starts queryable without waiting for simmering
- [x] **simmer_general job** — Optional/manual text general refinement, tracked per-iteration in `simmer_iterations` and `simmer_criterion_details`
- [x] **simmer_domain job** — Same two-phase loop for domain-specific specs
- [x] **simmer_domain_image job** — Single-phase per-domain image recognition-context refinement
- [x] **extract_batch / extract_batch_image jobs** — Worker runs simmered spec against target documents/images
- [x] **Domain spec cascade** — Deepest-first ancestor walk; additive extraction on top of general pass
- [x] **Content hash dedup** — Skip re-ingesting identical documents
- [x] **`GET /graph`** — cosmic_data_v4 format; golden-ratio color distribution; branching-level domain layout; trade routes; entity domain weights
- [x] **Cosmic visualization integration** — `/viz` page embeds `cosmic-viz.html` iframe; postMessage bridge to GalaxyPanel overlay
- [x] **GalaxyPanel** — entity, domain, and trade route panels; domain color donut for entities
- [x] **Simmer detail page** — `/simmer/{id}` with phase tabs, iteration list, per-criterion scores and evidence
- [x] **Extraction detail page** — `/extraction/{id}` with docs, entities (is_new flag), type distribution, normalization summary, reader pane
- [x] **Document reader** — `/documents/{id}/reader` with entity span highlighting, mention count, context snippets
- [x] **Subdomain discovery** — `POST /discover-subdomains` using `CLASSIFICATION_MODEL` to propose additive subdomain tags
- [x] **Upload page** (`/`) — drag-and-drop file upload + directory path ingest
- [x] **Pipeline page** (`/pipeline`) — stats bar, domain taxonomy, job list, simmer trigger buttons
- [x] **Entities page** (`/entities`) — paginated table with type/domain filters

### Originally Planned, Now Deferred or Changed

- **Phase B: Cosmic viz integration** — Shipped. Viz connects to live pipeline data via `/graph`.
- **Phase C: Search page** — Still deferred. The underlying retrieval capability exists (separate spark service); UI not built in this codebase yet.
- **User feedback / entity editing** — Not built. Would require new UI + entity edit endpoints.
- **Cloud deployment / Postgres migration** — Not done. Running on SQLite WAL locally.
- **Re-simmering triggers** — Auto-queue on threshold only. Quality-degradation-based re-simmering not implemented.
- **Domain embedding normalization** — Design exists, but live domain normalization is merge-map/exact-match only.

### Schema Additions Beyond Original Design

The original design doc listed a simpler schema. The following tables were added during implementation:

- `entity_embeddings` — cached entity embeddings for batch normalization
- `normalization_log` — audit trail for all merge decisions
- `normalization_review_queue` — ambiguous pairs for manual review
- `simmer_iterations` — per-iteration history from simmer-sdk
- `simmer_criterion_details` — per-criterion scores/evidence per iteration
- `documents.content_hash` — for deduplication
- `entity_sources.job_id` — to scope entities to a specific extraction job

---

## Context

All pipeline components are proven from experiments:
- 3-phase extraction pipeline (golden set → spec simmering → batch extract)
- Domain classification (32-domain taxonomy)
- Entity normalization cascade (14K→12K at scale)
- Simmer-SDK refinement loops

This service is the **wiring** — it orchestrates proven pieces, persists state, and exposes a UI for managing the pipeline. No new research, just integration.

## Architecture

```
docker compose up
├── orchestrator (FastAPI, port 8000)
│   ├── /ingest — accept files, trigger classification + extraction
│   ├── /domains — taxonomy view
│   ├── /entities — extracted entities
│   ├── /jobs — pipeline status
│   └── /simmer — manual trigger for general, domain text, or domain image spec
│
├── simmer-worker (Python, polls job queue)
│   ├── Watches SQLite jobs table every 5s
│   ├── Runs simmer-sdk refine() for general + domain text/image specs
│   └── Writes results back to SQLite
│
├── frontend (Next.js, port 3000)
│   ├── Upload page — drop files or point at directory
│   ├── Pipeline page — job status, domain taxonomy, doc counts
│   └── Entities page — table of extracted entities with filters
│
└── shared volume
    ├── orrery.db (SQLite)
    ├── documents/ (uploaded text files)
    └── specs/ (simmered spec files)
```

Three containers via docker compose. Orchestrator and simmer-worker share SQLite via volume mount. Frontend talks to orchestrator API.

## Roadmap Snapshot

- **Shipped:** Upload, classify, extract, image ingest/search, admin dashboard, cosmic visualization, multi-workspace support
- **Still active:** Search UX, entity editing/feedback, cloud deployment/Postgres migration, quality-based re-simmering triggers

## Data Model (SQLite)

**Note:** SQLite must be opened in WAL mode (`PRAGMA journal_mode=WAL`) since the orchestrator and simmer-worker write concurrently. Both processes should retry on SQLITE_BUSY.

```sql
-- Uploaded documents
documents (
  id            TEXT PRIMARY KEY,   -- uuid
  title         TEXT,
  source_path   TEXT,               -- original file path
  content       TEXT,
  content_hash  TEXT,               -- sha256 dedup key
  metadata      TEXT,               -- JSON: author, channel, source type, etc.
  content_type  TEXT,               -- text | image
  thumbnail_path TEXT,
  created_at    TIMESTAMP,
  status        TEXT                -- pending | classified | extracted | enriched
)

-- Document chunks (for provenance and re-extraction)
chunks (
  id            TEXT PRIMARY KEY,   -- uuid
  document_id   TEXT,               -- FK
  chunk_index   INTEGER,            -- order within document
  offset        INTEGER,            -- char offset in content
  length        INTEGER,
  text          TEXT,
  embedding     BLOB,
  image_embedding BLOB
)

-- Domain taxonomy
domains (
  id            TEXT PRIMARY KEY,   -- uuid
  path          TEXT UNIQUE,        -- e.g., "techniques/wet-blending"
  parent_path   TEXT,               -- nullable, FK to domains.path
  document_count INTEGER DEFAULT 0,
  spec_version  INTEGER,            -- null if no simmered spec
  created_at    TIMESTAMP
)

-- Domain merge map (normalization for domain labels)
domain_merge_map (
  from_label    TEXT PRIMARY KEY,
  to_path       TEXT                -- FK to domains.path
)

-- Document-to-domain assignments (many-to-many)
document_domains (
  document_id   TEXT,               -- FK
  domain_path   TEXT,               -- FK
  is_primary    BOOLEAN,
  confidence    REAL
)

-- Extracted entities
entities (
  id            TEXT PRIMARY KEY,   -- uuid
  canonical_name TEXT,
  type          TEXT,               -- Person, Technique, Paint, etc.
  created_at    TIMESTAMP
)

-- Entity sources (which doc/chunk produced this entity)
entity_sources (
  entity_id     TEXT,               -- FK
  document_id   TEXT,               -- FK
  chunk_id      TEXT,               -- FK to chunks.id
  extraction_pass TEXT,             -- general | domain-specific
  spec_version  INTEGER,
  job_id        TEXT
)

-- Entity merge map (normalization cache)
merge_map (
  from_name     TEXT PRIMARY KEY,
  to_entity_id  TEXT                -- FK to entities.id
)

-- Relationships between entities (populated by second extraction pass)
relationships (
  id            TEXT PRIMARY KEY,   -- uuid
  from_entity   TEXT,               -- FK
  to_entity     TEXT,               -- FK
  type          TEXT,
  weight        REAL,
  source_chunk  TEXT                -- FK to chunks.id
)

-- Pipeline jobs (simmering, batch extraction)
jobs (
  id            TEXT PRIMARY KEY,   -- uuid
  type          TEXT,               -- simmer_general | simmer_domain | simmer_domain_image | extract_batch | extract_batch_image
  target        TEXT,               -- domain path, or "general"
  status        TEXT,               -- queued | running | completed | failed
  config        TEXT,               -- JSON blob
  result        TEXT,               -- JSON blob
  created_at    TIMESTAMP,
  started_at    TIMESTAMP,
  completed_at  TIMESTAMP
)

-- Simmered specs (general + per-domain)
specs (
  id            TEXT PRIMARY KEY,   -- uuid
  domain_path   TEXT,               -- nullable (null = general spec)
  version       INTEGER,
  spec_content  TEXT,               -- the actual prompt/spec
  golden_set    TEXT,               -- JSON — golden entities
  score         REAL,               -- composite score from simmering
  media_type    TEXT DEFAULT 'text',
  created_at    TIMESTAMP
)
```

## API Endpoints

```
POST /ingest              Upload file(s), classify + extract synchronously
POST /ingest/directory    Point at a local path, ingest all text files

GET  /documents           List docs with status and domain assignments
GET  /documents/{id}      Single doc detail + extracted entities

GET  /domains             Taxonomy tree with doc counts and spec status
GET  /entities            Paginated entity list, filterable by type/domain
GET  /entities/{id}       Single entity with sources and merge history

GET  /jobs                Pipeline job status list
POST /simmer/general      Manually trigger general spec simmering
POST /simmer/{domain}     Manually trigger domain-specific text simmering
POST /simmer/{domain}/image
                          Manually trigger domain-specific image simmering

GET  /stats               Dashboard summary counts
```

## Pipeline Flow

### Ingest (synchronous)

```
POST /ingest (file upload)
│
├── 1. Store document in SQLite + documents/ volume
│   └── Chunk document → store chunks in chunks table
│
├── 2. Classify (CLASSIFICATION_MODEL, ~2-3s)
│   ├── Build classification excerpt:
│   │   ├── Doc < 6K chars → send whole thing
│   │   ├── Doc has structure → title + first section + last section + heading list
│   │   └── Doc > 6K chars → title + first 2K + middle 2K + last 2K chars
│   ├── Send excerpt + existing taxonomy to CLASSIFICATION_MODEL
│   ├── Get back: primary domain, secondary domains, confidence
│   ├── Normalize proposed domains against domain_merge_map
│   ├── Insert new domains into taxonomy if proposed (after normalization)
│   └── Update document status → "classified"
│
├── 3. General extraction
│   ├── Use latest simmered general text spec if one exists
│   ├── Otherwise use built-in general_text.md / general_image.md
│   ├── Extract entities + compute co-occurrence edges
│   └── Update document status → "extracted"
│
├── 4. Domain spec cascade
│   ├── For each assigned domain, walk ancestors deepest-first
│   ├── Run every available domain text spec not already seen for the doc
│   └── Add domain-specific entities on top of the general pass
│
├── 5. Check thresholds + triggers
│   └── Domain has no text spec + doc count >= DOMAIN_SPEC_THRESHOLD
│       → Queue simmer_domain job
│
└── Return: document ID, domains assigned, entity count, jobs queued
```

**Cold start is immediate extraction.** Built-in general text and image specs make the graph queryable from the first upload. General text simmering still exists, but it is a manual refinement path through `POST /simmer/general`, not an automatic first-upload gate.

**Domain extraction is additive.** A document extracted through the general spec keeps those entities. Domain-specific extraction adds richer, domain-specific entities on top. Status progresses: extracted → enriched.

### Extraction + Relationship Strategy

**Entity extraction** is the priority and where simmering applies. All extraction (general, domain) follows this pattern:

```
Pass 1: Entity extraction (LLM — built-in, simmered general, or simmered domain spec)
├── Run spec on each chunk → extract entities only
├── Deduplicate within document
├── Normalize inline: merge_map check → exact canonical name/type match → insert
└── Insert entities into entities table

Pass 2: Co-occurrence relationships (statistical — no LLM needed)
├── For each chunk, create edges between all entities found in that chunk
├── Weight by frequency (how many chunks they co-occur in)
└── Insert into relationships table as type "co_occurs"
```

**V1 relationships — two types, both free:**
- `co_occurs` — statistical, entities in same chunk. Computed from extraction output, no LLM call.
- `mentions` — document → entity provenance. Computed from entity_sources table.

`part_of` hierarchy is implicit in the data model (entities have types, types belong to domains). No need for explicit relationship rows.

Co-occurrence edges give 80% of the retrieval value for zero additional LLM cost. The existing warhammer pipeline's 1.3M co-occurrence edges already produce good search/RAG results. In a growing graph, hand-tuned edge types become maintenance burden — every new domain potentially needs new types, and classification errors compound.

**V2 (when needed):** Add LLM-based relationship extraction as a separate pass when multi-hop queries fail on co-occurrence alone. See `docs/research/relationship-extraction-analysis.md` for full analysis and trigger conditions.

### Domain Normalization

When the classifier proposes new domains, they go through normalization before insertion:

```
1. Check domain_merge_map — if this label was seen before, use canonical
2. Exact-match domains.path — if present, reuse existing path
3. Otherwise insert a new domain row
4. Derive parent_path from the slash-separated path
```

Runs inline during classification. Embedding similarity and LLM review for domain labels are planned/experimental, not current runtime behavior.

### Simmer Jobs (async, simmer-worker)

```
Simmer Job (general text, domain text, or domain image)
│
├── 1. Gather ~10 representative samples
│   ├── For general text: diverse chunks across documents
│   ├── For domain text: chunks from that domain
│   └── For domain image: images from that domain plus pre-scan notes
│
├── 2. Phase 1: Golden set simmering
│   ├── CLASSIFICATION_MODEL reads samples deeply
│   ├── Builds comprehensive entity set with types + relationships
│   ├── Seed ontology: Person, Organization, Topic, Event, Location, Thing
│   │   (for general spec — domain specs start from general spec types)
│   ├── Simmer-sdk refine() loop
│   │   ├── Judges evaluate: coverage, precision, taxonomy quality
│   │   └── SIMMER_ITERATIONS
│   └── Output: golden set (entities + types + relationships)
│
├── 3. Phase 2: Extraction spec simmering
│   ├── Template a Haiku prompt from the golden set
│   ├── Simmer-sdk refine() loop
│   │   ├── Evaluator: worker/src/jobs/evaluate_spec.py runs the candidate spec
│   │   ├── Judges review quantitative summary and raw eval JSON files
│   │   └── SIMMER_ITERATIONS
│   └── Output: simmered extraction spec (the prompt Haiku runs)
│
├── 4. Store spec + golden set in specs table
│
└── 5. Queue extract_batch for all target docs
```

Domain image simmering is single-phase. It starts from a static general image spec, builds a pre-scan-derived golden file, and refines only the `Domain Recognition Context` section. Image entity types are intentionally universal.

The text evaluator used by current jobs is `worker/src/jobs/evaluate_spec.py`; image jobs use `worker/src/jobs/evaluate_image_spec.py`.

### Batch Extraction (async, simmer-worker)

```
extract_batch job
│
├── For each document in target set:
│   ├── Run entity spec via Haiku on each chunk
│   │   ├── Deduplicate within document
│   │   ├── Normalize inline: merge_map check → exact match → insert
│   │   └── Insert entities
│   ├── Compute co-occurrence edges from extraction output
│   │   └── Insert relationships (type: co_occurs, weight: chunk frequency)
│   └── Update document status
│
└── Update document statuses → "extracted" (general) or "enriched" (domain)
```

## Frontend (Next.js + shadcn/ui)

### Upload Page (`/`)

- Drag-and-drop zone for files
- Text field to paste a local directory path
- Real-time status per file: uploading → classifying → extracting → done
- Summary: "5 files uploaded, 3 domains detected" then later "47 entities extracted"
- Simmering progress visible (links to Pipeline page job status)
- Temporary landing page — will be replaced with something better later

### Pipeline Page (`/pipeline`)

- Stats bar: total docs, entities, domains, active jobs
- Domain taxonomy as tree/table: path, doc count, spec status (none | simmering | v1 | v2)
- Jobs list: type, target, status, timestamps
- "Simmer General Spec" button for manual text general refinement
- Domain refine actions per row: text when enough text docs exist, image when enough image docs exist

### Entities Page (`/entities`)

- Paginated table: name, type, domain(s), source count, extraction pass
- Filter by type, domain, extraction pass
- Click entity → detail view with source documents and chunks

## Seed Ontology (General Spec Starting Point)

Entity types (from infodesk, expanded):
- **Person** — people, speakers, authors
- **Organization** — companies, groups, teams
- **Topic** — concepts, ideas, theories, fields
- **Event** — happenings, milestones, dates
- **Location** — places, regions, settings
- **Thing** — objects, tools, products, materials

Relationship types (V1 — both computed, no LLM):
- **co_occurs** — entities in same chunk (statistical)
- **mentions** — document → entity (provenance)

Simmering discovers domain-specific entity types (Technique, Paint, Model, Faction for miniature painting; Contract, Revenue, Product Line for business docs). Relationship types stay simple — richness comes from entity quality, not edge taxonomy.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Storage | SQLite WAL mode, volume-mounted | Simple, portable. WAL for concurrent writers. Swap to Postgres at prod |
| Containers | 3 via docker compose | Orchestrator + simmer worker + frontend. User runs `docker compose up` |
| Job queue | SQLite polling (5s) | No Redis/RabbitMQ needed at this scale |
| Classification | `CLASSIFICATION_MODEL`, synchronous | Fast enough (~2-3s), needs quality for domain discovery |
| Cold start | Built-in general specs run immediately | The graph is queryable from the first upload; simmering improves later |
| General extraction | Built-in spec, or latest manual simmered general text spec | Cheap baseline with optional corpus-specific refinement |
| Relationships V1 | Co-occurrence + mentions (both computed, no LLM) | Free from extraction output, proven in warhammer pipeline. LLM relationship pass deferred to V2 |
| Frontend | Next.js + shadcn/ui | Matches existing Noospheric app stack and live graph views |
| General spec | Built-in, with optional manual text simmer | Avoids a cold-start wait while preserving a refinement path |
| Entity normalization | Inline merge_map/exact match; batch embedding normalization via `/normalize` | Fast per-entity, accurate over time |
| Domain normalization | Inline merge_map/exact match/new insert | Conservative and predictable; embedding domain merges remain future work |
| Classification excerpt | Adaptive by doc size | < 6K whole doc, > 6K sample beginning + middle + end |
| Simmer trigger | Text domains auto at threshold; general text and domain image are manual | Keeps ingest immediate while letting users refine high-value areas |
| Golden set sample | 10 docs | Configurable, start conservative |

## Configuration

```yaml
# docker-compose.yml environment variables
ANTHROPIC_API_KEY: required
CLASSIFICATION_MODEL: claude-sonnet-4-6
EXTRACTION_MODEL: claude-haiku-4-5
GENERAL_SPEC_THRESHOLD: 10        # legacy setting; general text simmer is manual
DOMAIN_SPEC_THRESHOLD: 20         # docs in domain before auto-simmering domain spec
SIMMER_ITERATIONS: 3              # refinement iterations per simmer run
CHUNK_SIZE: 2000                  # chars per extraction chunk
WORKER_POLL_INTERVAL: 5           # seconds between job queue polls
```

## What This Does NOT Include (Deferred)

- Search page (Phase C)
- User feedback / entity editing
- Cloud deployment / Postgres migration
- Audio support
- Re-simmering triggers (quality degradation signals)
