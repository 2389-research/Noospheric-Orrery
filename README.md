# Noospheric Orrery

An adaptive knowledge graph pipeline. Upload documents and images, the system classifies them into domains, builds extraction specs through iterative refinement, extracts entities, and visualizes the result as an interactive galaxy map.

## What It Does

1. **Ingest** — upload text files or images (drag-and-drop, dual upload zones)
2. **Classify** — LLM assigns documents to a hierarchical domain taxonomy it builds incrementally
3. **Extract** — entities extracted immediately using built-in general specs (text + image)
4. **Simmer** — background worker iteratively refines domain-specific extraction specs
5. **Normalize** — entities deduplicated via string rules, embedding similarity, and review queue
6. **Visualize** — interactive galaxy map with UMAP-based semantic domain layout

The system is queryable from the first upload. Domain-specific richness comes later as simmering completes.

## Quick Start

```bash
git clone https://github.com/2389-research/Noospheric-Orrery.git
cd Noospheric-Orrery
cp .env.example .env    # edit with your credentials
docker compose up       # or: docker-compose up
```

Open http://localhost:3100 — no sign-in required.

> If you have an older standalone `docker-compose` binary (no `docker compose` v2 subcommand), use `docker-compose` in place of `docker compose` everywhere in this README. If you're upgrading from an older cloud-era checkout that ran a Firebase emulator container, add `--remove-orphans` to the first `up` to clean it up.

### Three Backend Options

Configure in `.env`:

| Backend | Config | Models | What You Need |
|---------|--------|--------|---------------|
| **AWS Bedrock** | `ANTHROPIC_BACKEND=bedrock` | Sonnet/Haiku | AWS credentials with Bedrock access |
| **Anthropic API** | `ANTHROPIC_BACKEND=gateway` | Sonnet/Haiku | Anthropic API key (`sk-ant-...`) |
| **Ollama (fully local)** | `ANTHROPIC_BACKEND=ollama` | gemma4:26b/e4b | [Ollama](https://ollama.com) installed, models pulled |

#### Fully Local Mode (Ollama)

```bash
# Install Ollama and pull models
ollama pull gemma4:26b    # 17GB — classification, judging, generation
ollama pull gemma4:e4b    # 9.6GB — extraction (follows structured prompts reliably)

# Configure .env
ANTHROPIC_BACKEND=ollama
OLLAMA_URL=http://host.docker.internal:11434
CLASSIFICATION_MODEL=gemma4:26b
EXTRACTION_MODEL=gemma4:e4b

# Launch
docker compose up
```

Zero cloud dependencies. Text and image extraction, search, simmering all work locally.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  orchestrator (FastAPI, :8100)                          │
│  Ingest → Classify → Extract → Normalize → Search       │
│  Image serving, graph data, WebSocket broadcasts        │
└──────────────────────┬──────────────────────────────────┘
                       │ shared SQLite (WAL mode)
┌──────────────────────┴──────────────────────────────────┐
│  worker (Python, background)                            │
│  Polls jobs table every 5s                              │
│  Runs simmer (text + image), extract_batch, normalize   │
│  Uses simmer-sdk with direct API agent loop (no CLI)    │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  frontend (Next.js, :3100)                              │
│  Upload / Pipeline / Entities / Orrery / Simmer detail  │
│  Multi-noosphere, image search, ImagePane               │
└─────────────────────────────────────────────────────────┘
```

All LLM calls go through `orrery-relay` (`packages/orrery-relay/`), which handles backend routing:
- **Bedrock/Gateway**: Anthropic SDK with tool_use for structured output
- **Ollama**: Native `/api/chat` endpoint — supports text, vision, and structured output

## Features

### Text Pipeline
- Upload `.txt`, `.md`, `.json`, `.csv`
- Classification into hierarchical domains
- Entity extraction with general spec (immediate) + domain specs (after simmering)
- Co-occurrence edges, domain cascade, normalization

### Image Pipeline
- Upload `.jpg`, `.png`, `.webp`, `.gif`
- Vision LLM describes and classifies images
- Entity extraction from image descriptions
- Image search (toggle in orrery view)
- ImagePane renders actual images with entity tags

### Simmering (Spec Refinement)
- **General specs**: Built-in defaults for text and image make every upload queryable immediately; `/simmer/general` can manually refine the text general spec for a corpus
- **Text domains**: 2-phase (golden set → extraction spec), board judge with 2 panelists
- **Image domains**: Single-phase per-domain recognition context layered on the static general image spec
- **API backends**: Uses simmer-sdk direct API agent loop (2x faster than CLI, no hangs)
- **Ollama**: Deterministic pipeline — pre-scan → evaluate → review → score → generate
- Pipeline page shows per-domain text/image breakdown with conditional refine buttons

### UMAP Domain Layout
- 100 anchor domains seed the UMAP space for well-distributed initial layout
- `transform()` places new domains without re-fitting (stable positions)
- `NUMBA_CPU_NAME=generic` fixes ARM Docker SIGILL (numba#10388)

### Multi-Noosphere
- Each noosphere is a fully isolated knowledge graph — its own SQLite file under `data/workspaces/{id}/`, tracked by a JSON registry at `data/workspaces/registry.json`
- Create/switch noospheres from the UI at `/settings/noospheres`, or via the `/workspaces` API (the endpoint keeps the legacy name from an earlier cloud-era design)
- API calls scope to a noosphere via the `X-Workspace-Id` header; omitting it targets the `default` noosphere

## Running Without Docker

```bash
# Orchestrator
cd orchestrator && pip install -e . && uvicorn src.main:app --reload --port 8000

# Worker (separate terminal)
cd worker && python -m src.main

# Frontend (separate terminal)
cd frontend && NEXT_PUBLIC_AUTH_MODE=noop BACKEND_URL=http://localhost:8000 npm run dev
```

## Testing

```bash
# Run in Docker (recommended — matches production environment)
docker run --rm \
  -v $(pwd)/orchestrator/tests:/app/orchestrator/tests \
  -v $(pwd)/orchestrator/src:/app/orchestrator/src \
  -v $(pwd)/orchestrator/specs:/app/orchestrator/specs \
  -w /app/orchestrator \
  ghcr.io/2389-research/orrery-orchestrator:latest \
  sh -c "uv pip install pytest httpx && uv run python -m pytest tests/ -v"
```

61 tests covering: DB schema + migrations, config defaults, auth/workspace CRUD, ingest pipeline, image pipeline, entity normalization, domain layout, search, simmer triggers.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/ingest` | Upload file (text or image) |
| `GET` | `/documents` | List documents with content_type |
| `GET` | `/domains` | Domain taxonomy with text/image counts |
| `GET` | `/entities` | Entities, filterable by type/domain/job |
| `GET` | `/search?q=...&include_images=true` | Hybrid search with optional image results |
| `GET` | `/graph` | Graph data (UMAP positions, entities, trade routes) |
| `GET` | `/images/{id}` | Serve image file |
| `POST` | `/simmer/general` | Trigger text spec simmering |
| `POST` | `/simmer/{domain_path}` | Trigger domain-specific text simmering |
| `POST` | `/simmer/{domain_path}/image` | Trigger domain-specific image simmering |
| `GET` | `/stats` | Counts (documents, entities, domains, images, active jobs) |
| `GET` | `/workspaces` | List noospheres |
| `POST` | `/workspaces` | Create a noosphere |
| `PATCH` | `/workspaces/{id}` | Rename a noosphere |
| `DELETE` | `/workspaces/{id}` | Archive a noosphere (soft delete) |
| `GET` | `/health` | Health check |

All data endpoints (ingest, documents, entities, graph, search, simmer, …) accept an optional `X-Workspace-Id: <id>` header to scope the request to a specific noosphere. Omit the header to target `default`. The `/workspaces` path is the legacy name from a cloud-era multi-tenancy design — the UI calls these "noospheres."

Full interactive docs at http://localhost:8100/docs

## Design Principles

1. **Extraction specs are the artifact that improves, not the code.** The pipeline stays fixed; specs evolve through simmering.
2. **Expensive work is amortized.** Classification and simmering happen once. Per-document extraction is cheap.
3. **Queryable from moment one.** Every document produces entities immediately via built-in general specs.
4. **Works offline.** Ollama backend requires zero internet after model download.
5. **Prompt quality > model quality.** A simmered spec on a small model outperforms a generic prompt on a large one.
