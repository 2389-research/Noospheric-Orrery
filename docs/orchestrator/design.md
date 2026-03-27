# Orchestrator Service — Design Spec

**Date:** 2026-03-27
**Status:** Approved
**Purpose:** FastAPI orchestrator + simmer worker + Next.js dashboard to wire together the validated extraction pipeline

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
│   └── /simmer — manual trigger for general or domain spec
│
├── simmer-worker (Python, polls job queue)
│   ├── Watches SQLite jobs table every 5s
│   ├── Runs simmer-sdk refine() for general + domain specs
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

## Roadmap

- **Phase A (this spec):** Upload + classify + extract + admin dashboard
- **Phase B (later):** Embed cosmic visualization, graph wired to live pipeline state
- **Phase C (later):** Search page, full Noospheric app integration

## Data Model (SQLite)

**Note:** SQLite must be opened in WAL mode (`PRAGMA journal_mode=WAL`) since the orchestrator and simmer-worker write concurrently. Both processes should retry on SQLITE_BUSY.

```sql
-- Uploaded documents
documents (
  id            TEXT PRIMARY KEY,   -- uuid
  title         TEXT,
  source_path   TEXT,               -- original file path
  content       TEXT,
  metadata      TEXT,               -- JSON: author, channel, source type, etc.
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
  text          TEXT
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
  spec_version  INTEGER
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
  type          TEXT,               -- simmer_general | simmer_domain | extract_batch
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
POST /simmer/{domain}     Manually trigger domain-specific simmering

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
├── 2. Classify (Sonnet, ~2-3s)
│   ├── Build classification excerpt:
│   │   ├── Doc < 6K chars → send whole thing
│   │   ├── Doc has structure → title + first section + last section + heading list
│   │   └── Doc > 6K chars → title + first 2K + middle 2K + last 2K chars
│   ├── Send excerpt + existing taxonomy to Sonnet
│   ├── Get back: primary domain, secondary domains, new domain proposals
│   ├── Normalize proposed domains against domain_merge_map
│   ├── Insert new domains into taxonomy if proposed (after normalization)
│   └── Update document status → "classified"
│
├── 3. Has simmered general spec?
│   ├── YES → Extract with general spec (Haiku) + compute co-occurrence edges
│   │   └── Update document status → "extracted"
│   └── NO → Document stays "classified", awaiting spec
│
├── 4. Check thresholds + triggers
│   ├── No general spec → Auto-queue simmer_general job
│   │   (first upload triggers this — user watches simmering happen)
│   ├── Domain has specific spec → Queue domain re-extraction (async, additive)
│   └── Domain has no spec + doc count >= threshold → Queue simmer_domain job
│
└── Return: document ID, domains assigned, entity count (if spec exists), jobs queued
```

**Cold start: simmering IS the first step.** When a user uploads their first batch of documents, the system classifies them into domains, then immediately begins simmering a general spec tailored to this corpus. The user watches the simmering job progress in the UI. Once the general spec completes, batch extraction runs on all classified documents. There is no throwaway seed extraction — the first extraction uses a spec built for this corpus.

The first simmer triggers on the first upload, not at a threshold. The user experience is: upload → classify (fast) → simmer general spec (minutes, visible progress) → extract everything (fast). The wait is the point — the system is learning what matters in your corpus.

**Domain extraction is additive.** A document extracted through the general spec keeps those entities. Domain-specific extraction adds richer, domain-specific entities on top. Status progresses: extracted → enriched.

### Extraction + Relationship Strategy

**Entity extraction** is the priority and where simmering applies. All extraction (general, domain) follows this pattern:

```
Pass 1: Entity extraction (LLM — simmered spec via Haiku)
├── Run spec on each chunk → extract entities only
├── Deduplicate within document
├── Normalize: merge_map check → embed → compare to existing clusters
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
2. Embed proposed label (all-MiniLM-L6-v2)
3. Compare to existing domain embeddings (cosine similarity)
4. If similarity > 0.85 to existing domain → merge (use existing)
5. If 0.7-0.85 → flag for LLM review (Sonnet confirms merge or keep)
6. If < 0.7 → new domain, insert into taxonomy
7. Update domain_merge_map with decision
```

Runs inline during classification. Prevents domain proliferation.

### Simmer Jobs (async, simmer-worker)

```
Simmer Job (general or domain-specific)
│
├── 1. Gather ~10 representative samples
│   ├── For general: diverse docs across domains
│   └── For domain: docs from that domain, varied subtopics
│
├── 2. Phase 1: Golden set simmering
│   ├── Sonnet reads samples deeply
│   ├── Builds comprehensive entity set with types + relationships
│   ├── Seed ontology: Person, Organization, Topic, Event, Location, Thing
│   │   (for general spec — domain specs start from general spec types)
│   ├── Simmer-sdk refine() loop
│   │   ├── Evaluator: score_golden_set.py --docs {candidate_path}
│   │   ├── Judges evaluate: coverage, precision, taxonomy quality
│   │   └── ~4-5 iterations
│   └── Output: golden set (entities + types + relationships)
│
├── 3. Phase 2: Extraction spec simmering
│   ├── Template a Haiku prompt from the golden set
│   ├── Simmer-sdk refine() loop
│   │   ├── Evaluator: eval_runner_haiku.py runs spec against held-out docs
│   │   ├── Scorer: eval_scorer.py does fuzzy match against golden set
│   │   └── ~4-5 iterations
│   └── Output: simmered extraction spec (the prompt Haiku runs)
│
├── 4. Store spec + golden set in specs table
│
└── 5. Queue extract_batch for all target docs
```

**Evaluator scripts** live in the simmer-worker container at `/app/evaluators/`:
- `score_golden_set.py` — scores golden set candidates on coverage, precision, taxonomy quality
- `eval_runner_haiku.py` — runs an extraction spec against sample documents via Haiku
- `eval_scorer.py` — fuzzy-matches extracted entities against golden set (precision + recall)

These are the same scripts validated in the extraction pipeline experiments.

### Batch Extraction (async, simmer-worker)

```
extract_batch job
│
├── For each document in target set:
│   ├── Run entity spec via Haiku on each chunk
│   │   ├── Deduplicate within document
│   │   ├── Normalize: merge_map check → embed → compare to existing clusters
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
- Real-time status per file: uploading → classifying → classified (awaiting spec)
- When general spec completes: extracting → done
- Summary: "5 files uploaded, 3 domains detected" then later "47 entities extracted"
- Simmering progress visible (links to Pipeline page job status)
- Temporary landing page — will be replaced with something better later

### Pipeline Page (`/pipeline`)

- Stats bar: total docs, entities, domains, active jobs
- Domain taxonomy as tree/table: path, doc count, spec status (none | simmering | v1 | v2)
- Jobs list: type, target, status, timestamps
- "Simmer General Spec" button (enabled when no spec + docs >= 10)
- "Simmer Domain" button per domain row

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
| Classification | Sonnet, synchronous | Fast enough (~2-3s), needs quality for domain discovery |
| Cold start | Simmer general spec on first upload | No throwaway extraction — first spec is tailored to this corpus |
| General extraction | Haiku with simmered spec | Cheap, proven from experiments |
| Relationships V1 | Co-occurrence + mentions (both computed, no LLM) | Free from extraction output, proven in warhammer pipeline. LLM relationship pass deferred to V2 |
| Frontend | Next.js + shadcn/ui | Matches existing Noospheric app stack, easy to integrate cosmic viz in phase B |
| General spec | Simmered, not hardcoded | Seed ontology + simmer discovers corpus-specific types |
| Entity normalization | Incremental (merge_map + embed), full batch periodic | Fast per-entity, accurate over time |
| Domain normalization | Inline during classification (embed + compare + LLM review) | Prevents domain proliferation |
| Classification excerpt | Adaptive by doc size | < 6K whole doc, > 6K sample beginning + middle + end |
| Simmer trigger | Auto at threshold + manual button | Auto for convenience, manual for testing |
| Golden set sample | 10 docs | Configurable, start conservative |

## Configuration

```yaml
# docker-compose.yml environment variables
ANTHROPIC_API_KEY: required
CLASSIFICATION_MODEL: claude-sonnet-4-20250514
EXTRACTION_MODEL: claude-haiku-4-20250514
GENERAL_SPEC_THRESHOLD: 10        # docs before auto-simmering general spec
DOMAIN_SPEC_THRESHOLD: 20         # docs in domain before auto-simmering domain spec
SIMMER_ITERATIONS: 5              # refinement iterations per simmer run
CHUNK_SIZE: 2000                  # chars per extraction chunk
WORKER_POLL_INTERVAL: 5           # seconds between job queue polls
```

## What This Does NOT Include (Deferred)

- Cosmic visualization integration (Phase B)
- Search page (Phase C)
- User feedback / entity editing
- Cloud deployment / Postgres migration
- Multi-modal document support (images, audio)
- Re-simmering triggers (quality degradation signals)
