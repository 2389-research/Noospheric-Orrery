# Noospheric Orrery

An adaptive knowledge graph extraction pipeline with a cosmic visualization. Upload documents, watch the system discover domains, build extraction specs through iterative refinement, and explore the resulting graph as an interactive galaxy map.

Built on miniature painting YouTube tutorials as the proof-of-concept domain. The pipeline is domain-agnostic — it discovers entity types, relationship types, and domain taxonomy from the corpus itself.

## What It Does

1. **Ingest** — drop text files or point at a directory
2. **Classify** — Claude Sonnet assigns documents to a hierarchical domain taxonomy it builds incrementally
3. **Simmer** — a background worker uses simmer-sdk to iteratively refine a golden entity set, then a Haiku extraction spec tuned to your corpus
4. **Extract** — Claude Haiku runs the simmered spec cheaply across all documents; domain-specific specs add richness on top
5. **Normalize** — entities are deduplicated via string rules + embedding similarity + LLM review for ambiguous pairs
6. **Visualize** — an interactive galaxy map renders domains as nebulae and entities as stars

The system is queryable from the first upload. First-pass extraction uses a generic spec immediately. Domain-specific richness comes later as simmering completes.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  orchestrator (FastAPI, :8100)                          │
│  Ingest → Classify → Extract → Normalize                │
│  Exposes REST API consumed by frontend                  │
└──────────────────────┬──────────────────────────────────┘
                       │ shared SQLite (WAL mode)
┌──────────────────────┴──────────────────────────────────┐
│  worker (Python, background)                            │
│  Polls jobs table every 5s                              │
│  Runs simmer_general, simmer_domain, extract_batch      │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  frontend (Next.js, :3100)                              │
│  Upload / Pipeline / Entities / Viz / Simmer / Extract  │
└─────────────────────────────────────────────────────────┘

External:
  AWS Bedrock  — all Claude API calls
  simmer-sdk   — iterative refinement loops
```

All three services run via `docker compose up`. Orchestrator and worker share a SQLite volume at `/data/orrery.db`.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Orchestrator | Python 3.11+, FastAPI, Uvicorn |
| Worker | Python 3.11+, asyncio polling loop |
| AI calls | AWS Bedrock via `anthropic[bedrock]` SDK |
| Classification model | `claude-sonnet-4-20250514` |
| Extraction model | `claude-haiku-4-20250514` (or haiku-4-5) |
| Iterative refinement | simmer-sdk |
| Embeddings | all-MiniLM-L6-v2 (sentence-transformers, deferred) |
| Storage | SQLite WAL mode |
| Frontend | Next.js, shadcn/ui, TypeScript |
| Cosmic viz | Canvas2D self-contained HTML, iframe + postMessage |
| Containers | Docker Compose |

## Running Locally

### Prerequisites

- Docker and Docker Compose
- AWS account with Bedrock access and cross-region inference enabled for `us-east-1`

### Environment Variables

Copy `.env.example` to `.env` (or create `.env`):

```bash
AWS_ACCESS_KEY=your_key
AWS_SECRET_KEY=your_secret
AWS_REGION=us-east-1

# Models (Bedrock cross-region inference profile IDs)
CLASSIFICATION_MODEL=us.anthropic.claude-sonnet-4-20250514-v1:0
EXTRACTION_MODEL=us.anthropic.claude-haiku-4-20250514-v1:0

# Thresholds
GENERAL_SPEC_THRESHOLD=10   # docs before auto-triggering general spec simmer
DOMAIN_SPEC_THRESHOLD=20    # docs in a domain before auto-triggering domain simmer
SIMMER_ITERATIONS=5
CHUNK_SIZE=2000
WORKER_POLL_INTERVAL=5
```

### Docker Compose (recommended)

```bash
docker compose up
```

Services start on:
- Frontend: http://localhost:3100
- Orchestrator API: http://localhost:8100
- API docs: http://localhost:8100/docs

Data persists in the `orrery-data` Docker volume.

### Running Without Docker

The orchestrator and worker can run outside containers against `~/orrery-data/` directly. An env script is kept at `/tmp/run-orchestrator.sh` with all environment variables pre-set.

**Orchestrator:**
```bash
source /tmp/run-orchestrator.sh
cd orchestrator
pip install -e ".[dev]"
uvicorn src.main:app --reload --port 8000
```

**Worker:**
```bash
source /tmp/run-orchestrator.sh
cd worker
pip install -e ".[dev]"
# Install simmer-sdk from local checkout
pip install -e /path/to/simmer-sdk
python -m src.main
```

**Frontend:**
```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

The frontend runs on port 3000 by default.

## Pipeline Flow

```
POST /ingest (file upload or directory path)
│
├── 1. Store document + chunks in SQLite
│
├── 2. Classify (Sonnet, ~2-3s)
│   ├── Build adaptive excerpt (whole doc if < 6K chars, else title + start + middle + end)
│   ├── Classify against existing taxonomy
│   ├── Normalize proposed domains (embed → cosine similarity → LLM review for ambiguous)
│   └── Insert new domains, assign document
│
├── 3. Extract with general spec (if one exists)
│   ├── Run simmered spec via Haiku on each chunk
│   ├── Normalize entities (merge_map → embed → compare to cluster)
│   └── Compute co-occurrence edges (entities in same chunk → weight by frequency)
│
├── 4. Cascade domain-specific specs (deepest domain first, then ancestors)
│   └── Additive: domain entities added on top of general extraction
│
└── 5. Check thresholds → queue jobs
    ├── No general spec → queue simmer_general (auto, first upload)
    └── Domain >= threshold + no spec → queue simmer_domain
```

**Simmer jobs** run in the worker and produce:
- Phase 1: Golden set (representative entities for the domain — simmered against coverage/precision/taxonomy criteria)
- Phase 2: Extraction spec (Haiku prompt tuned to reproduce the golden set — simmered against recall/precision/format)

Once a spec exists, all queued documents are extracted via `extract_batch`.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/ingest` | Upload a file (multipart) |
| `POST` | `/ingest/directory` | Ingest all `.txt/.md/.json/.csv` from a local path |
| `GET` | `/documents` | List documents with status and domains |
| `GET` | `/documents/{id}` | Document detail with entities |
| `GET` | `/documents/{id}/reader` | Document with entity spans for highlighted reading |
| `GET` | `/domains` | Domain taxonomy with doc counts and spec status |
| `GET` | `/entities` | Paginated entities, filterable by `type`, `domain`, `job_id` |
| `GET` | `/entities/{id}` | Entity detail with sources and merge history |
| `GET` | `/entities/{id}/cooccurrences` | Entities that co-occur with this entity |
| `GET` | `/jobs` | Pipeline job list, filterable by `status` |
| `GET` | `/jobs/{id}/iterations` | Simmer iteration history for a job (phases + per-criterion scores) |
| `POST` | `/simmer/general` | Manually trigger general spec simmering |
| `POST` | `/simmer/{domain_path}` | Manually trigger domain-specific simmering |
| `GET` | `/stats` | Dashboard counts (documents, entities, domains, active jobs) |
| `POST` | `/normalize` | Run full normalization cascade on all entities |
| `GET` | `/normalize/summary` | Normalization merge history |
| `GET` | `/normalize/review` | Ambiguous entity pairs pending manual review |
| `POST` | `/normalize/review/{id}` | Resolve a review item (`action=merge` or `keep_separate`) |
| `POST` | `/discover-subdomains` | Run subdomain discovery across all extracted docs |
| `GET` | `/graph` | Graph data in `cosmic_data_v4` format for the viz |
| `GET` | `/health` | Health check |

Full interactive docs at `/docs` (Swagger) and `/redoc`.

## Frontend Pages

| Route | Description |
|-------|-------------|
| `/` | Upload page — drag-and-drop files or paste a directory path |
| `/pipeline` | Job status, domain taxonomy tree, spec maturity, "Simmer" buttons |
| `/entities` | Paginated entity table with type/domain filters |
| `/viz` | Cosmic galaxy map (iframe + postMessage panel) |
| `/simmer/{id}` | Simmer job detail — iteration history, per-criterion scores, phase tabs |
| `/extraction/{id}` | Batch extraction detail — docs processed, entities extracted, normalization summary, reader view |

## Data Model (Key Tables)

| Table | Purpose |
|-------|---------|
| `documents` | Uploaded files with status (`pending → classified → extracted → enriched`) |
| `chunks` | Fixed-size chunks of each document for extraction provenance |
| `domains` | Hierarchical taxonomy (`path` like `techniques/wet-blending`) |
| `domain_merge_map` | Normalization decisions for domain labels |
| `document_domains` | Many-to-many: which domains a document belongs to |
| `entities` | Canonical entities with type |
| `entity_sources` | Which document/chunk produced each entity, which spec version |
| `merge_map` | Entity normalization cache (`from_name → to_entity_id`) |
| `relationships` | Co-occurrence and typed edges between entities |
| `jobs` | Pipeline jobs (`simmer_general`, `simmer_domain`, `extract_batch`) |
| `specs` | Simmered extraction specs with golden set and composite score |
| `simmer_iterations` | Per-iteration history from simmer-sdk (scores, key change, ASI) |
| `entity_embeddings` | Cached embeddings for normalization (deferred) |
| `normalization_review_queue` | Ambiguous entity pairs for manual review |

Full schema: `/orchestrator/src/db.py`

## Design Docs

| Document | Location |
|----------|----------|
| Orchestrator design spec | `docs/orchestrator/design.md` |
| Orchestrator implementation plan | `docs/orchestrator/implementation-plan.md` |
| Pipeline specification | `docs/pipeline-spec.md` |
| Extraction pipeline learnings | `docs/extraction-pipeline/` |
| Domain classification | `docs/domain-classification/` |
| Cosmic visualization | `docs/cosmic-visualization/` |
| Architecture reference | `docs/ARCHITECTURE.md` |

## Design Principles

1. **Extraction specs are the artifact that improves, not the code.** The pipeline stays fixed; specs evolve through simmering.
2. **Expensive work is amortized.** Domain classification and spec simmering happen once. Per-document extraction is cheap.
3. **Queryable from moment one.** Every document produces entities immediately. Domain richness comes later.
4. **The graph is both output and context.** Accumulated structure informs future extraction.
5. **Prompt quality > model quality.** A simmered Haiku spec outperforms a generic Sonnet prompt.
