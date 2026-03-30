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
| Embeddings | all-MiniLM-L6-v2 (sentence-transformers) |
| Semantic search | FAISS IndexFlatIP + query expansion via Haiku |
| Domain layout | UMAP on domain embeddings (persistent, stable) |
| Storage | SQLite WAL mode |
| Frontend | Next.js 16, shadcn/ui, TypeScript |
| Cosmic viz | Canvas2D ES modules, iframe + postMessage |
| MCP server | stdio server for AI agent integration |
| Containers | Docker Compose |

## Quick Start

### Prerequisites

- Docker and Docker Compose
- AWS account with Bedrock access (cross-region inference enabled for `us-east-1`)
- Access to [simmer-sdk](https://github.com/2389-research/simmer-sdk)

### Setup

```bash
# 1. Clone repos
git clone <noospheric-orrery-repo>
git clone https://github.com/2389-research/simmer-sdk.git

# 2. Copy simmer-sdk into worker build context
cp -r simmer-sdk/ Noospheric-Orrery/worker/simmer-sdk/

# 3. Configure environment
cd Noospheric-Orrery
cp .env.example .env
# Edit .env with your AWS credentials

# 4. Launch
docker compose up
```

Services start on:
- **Frontend**: http://localhost:3100 (upload, pipeline, entities, galaxy viz)
- **Orchestrator API**: http://localhost:8100 (REST API + WebSocket)
- **API docs**: http://localhost:8100/docs (Swagger)

Data persists in the `orrery-data` Docker volume.

### First Steps

1. Open http://localhost:3100 and upload a text/markdown file
2. The pipeline automatically: classifies into domains, extracts entities, indexes for search
3. Go to `/viz` to see the galaxy map — zoom in for sector detail, double-click entities for star view
4. Use `/pipeline` to monitor jobs, trigger simmering, run normalization

### Running Without Docker (Dev Mode)

```bash
# Create venvs
cd orchestrator && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && cd ..
cd worker && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pip install -e ../simmer-sdk && cd ..
cd frontend && npm install && cd ..

# Set environment variables
cp .env.example .env  # edit with your AWS creds
export $(cat .env | xargs)
export DB_PATH=$HOME/orrery-data/orrery.db
export DOCUMENTS_DIR=$HOME/orrery-data/documents
export SPECS_DIR=$HOME/orrery-data/specs

# Start services (each in its own terminal)
cd orchestrator && .venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8100
cd worker && .venv/bin/python -m src.main
cd frontend && NEXT_PUBLIC_API_URL=http://localhost:8100 npm run dev -- -p 3100
```

### MCP Server (for AI agents)

The orchestrator includes an MCP server for Claude Code or other MCP-compatible agents:

```bash
cd orchestrator
source ../.env
export DB_PATH=$HOME/orrery-data/orrery.db
.venv/bin/python -m src.mcp_server
```

Exposes tools: `search_knowledge_graph`, `get_entity`, `get_document`, `list_domains`, `list_entities`. Searches trigger the galaxy viz glow animation via WebSocket when the orchestrator is running.

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
| `GET` | `/search` | Hybrid search: query expansion + FAISS semantic + exact match + RRF fusion |
| `POST` | `/search/rebuild` | Rebuild FAISS indexes from stored embeddings |
| `POST` | `/reclassify` | Re-run classifier on all documents (additive domains) |
| `GET` | `/entities/{id}/star-graph` | 2-hop local graph: entity + docs + co-entities with shared doc IDs |
| `GET` | `/graph` | Graph data (UMAP positions, entities, trade routes) for the viz |
| `GET` | `/graph/umap` | Same as /graph, forces fresh UMAP recomputation |
| `GET` | `/health` | Health check |

Full interactive docs at `/docs` (Swagger) and `/redoc`.

## Frontend Pages

| Route | Description |
|-------|-------------|
| `/` | Upload page — drag-and-drop files or paste a directory path |
| `/pipeline` | Job status, domain taxonomy tree, spec maturity, "Simmer" buttons |
| `/entities` | Paginated entity table with type/domain filters |
| `/viz` | Galaxy map — zoom for sector detail, double-click entity for star view, search to navigate |
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
