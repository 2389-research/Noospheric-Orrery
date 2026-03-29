# Implementation Notes — Gotchas, Decisions, and Why Things Are the Way They Are

For any agent or developer picking up this codebase. Read this before making changes.

## Architecture Decisions

### Why SQLite, not Postgres
SQLite with WAL mode handles concurrent reads from orchestrator + worker. Data lives at `~/orrery-data/orrery.db` (NOT in the repo). At production scale, swap to Postgres — the queries are standard SQL, nothing SQLite-specific.

### Why Bedrock, not direct Anthropic API
The Anthropic API account had no credits. All LLM calls go through AWS Bedrock. This means:
- Use `AsyncAnthropicBedrock` not `AsyncAnthropic`
- Model IDs have the `us.` prefix: `us.anthropic.claude-sonnet-4-20250514-v1:0`
- Need AWS credentials (access key + secret + region), NOT ANTHROPIC_API_KEY
- The simmer-sdk 0.2.0+ supports Bedrock via `api_provider="bedrock"` parameter

### Why two separate containers (orchestrator + worker)
The orchestrator handles fast synchronous API requests. The worker handles slow async jobs (simmering takes 30-50 min). They share the SQLite DB via the same file path. If they were one process, a simmering job would block API requests.

### Why the cosmic viz is a self-contained HTML file
Canvas2D at 60fps doesn't work well as a React component — the render loop needs direct canvas access without React reconciliation overhead. The viz communicates with React via postMessage through an iframe boundary. This is intentional.

## Data Persistence

**CRITICAL: Data lives at `~/orrery-data/`, NOT in the repo.**

The env script at `/tmp/run-orchestrator.sh` sets:
```
DB_PATH=$HOME/orrery-data/orrery.db
DOCUMENTS_DIR=$HOME/orrery-data/documents
SPECS_DIR=$HOME/orrery-data/specs
```

If you remove a git worktree, the data survives. If you `rm -rf` the data directory, everything is lost — simmered specs (~50 min each), embeddings, entities, all of it.

## Gotchas

### Bedrock Model IDs
- Sonnet: `us.anthropic.claude-sonnet-4-20250514-v1:0`
- Haiku: `us.anthropic.claude-haiku-4-5-20251001-v1:0`
- There is NO `claude-haiku-4-20250514` on Bedrock — it doesn't exist. Use `haiku-4-5-20251001`.
- The `us.` prefix is required for cross-region inference profiles.

### SQLite WAL Mode
Both orchestrator and worker write to the same DB. WAL mode is set in `db.py`:
```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")
```
Without WAL, concurrent writes will fail with SQLITE_BUSY.

### Entity birthScale
Domain and entity nodes start with `birthScale: 0.01` (nearly invisible). The `state.update()` method grows them to 1.0 over ~66 frames. If you add new rendering and things are invisible, check birthScale.

### CORS
The orchestrator has `allow_origins=["*"]` — wide open for local dev. WebSocket connections are NOT affected by CORS middleware (Starlette skips WebSocket scopes). If WebSocket connections fail with 403, the issue is NOT CORS — check the endpoint type hints.

### Domain Path Format
Domain paths are hierarchical strings: `business/fundraising/investor_meetings`. The `/` is a path separator. When querying with `GET /entities?domain=X`, it uses `LIKE X%` to include subdomains.

### Content Hash Dedup
Documents are deduped by SHA-256 of content, not by title. Re-ingesting the same file is a no-op. If you need to re-process a document, delete it from the DB first.

### Embedding Storage
Entity and chunk embeddings are stored as BLOBs in SQLite (`entities.embedding`, `chunks.embedding`). FAISS indexes are rebuilt from these on startup. New entities/chunks need `POST /search/rebuild` or `embed_new_entities()`/`embed_new_chunks()` calls after extraction.

### The Env Script
`/tmp/run-orchestrator.sh` contains AWS credentials and all config. It's in /tmp so it doesn't persist across reboots. Recreate it:
```bash
cat > /tmp/run-orchestrator.sh << 'EOF'
export AWS_ACCESS_KEY=<key>
export AWS_SECRET_KEY='<secret>'
export AWS_REGION=us-east-1
export CLASSIFICATION_MODEL=us.anthropic.claude-sonnet-4-20250514-v1:0
export EXTRACTION_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0
export DB_PATH=$HOME/orrery-data/orrery.db
export DOCUMENTS_DIR=$HOME/orrery-data/documents
export SPECS_DIR=$HOME/orrery-data/specs
export GENERAL_SPEC_THRESHOLD=10
export DOMAIN_SPEC_THRESHOLD=20
export SIMMER_ITERATIONS=5
export CHUNK_SIZE=2000
export WORKER_POLL_INTERVAL=5
EOF
```

### Simmer-SDK
Installed from local path: `/Users/michaelsugimura/Documents/GitHub/simmer-sdk/`. Version 0.2.1 with Bedrock support + judgment file writing. If you pip install in a new venv, you need:
```bash
pip install -e /path/to/simmer-sdk/
```

### Frontend Next.js 16
This is NOT the Next.js you know. Read `frontend/AGENTS.md`. Breaking changes from older versions. Use `useParams()` from `next/navigation`, not `useRouter()`.

## Four Visualization Views

Currently implemented as separate tabs (not unified zoom transitions yet):

### Galaxy View (`/viz`, accent: blue/cyan)
- All domains as nebulae (3 states: unformed, simmering, formed)
- Cluster clouds from UMAP proximity
- Trade routes with search-triggered pulse animation
- Pulses only fire on search — no ambient random pulses
- Search glow cascade: entities flash → domains brighten → route pulses travel → arrival ripple

### Sector View (`/viz/sector?domain=path`, accent: amber)
- Focused cluster of domains with richer labels (spec version, doc count, entity count)
- Trade route weight labels on routes ≥ 20
- Top 40 entities as small stars, bridge entities with halo rings
- Edge domains from connected clusters at periphery
- Hover: tooltips on domains, routes, entities

### System View (`/viz/system?domain=path`, accent: purple)
- Single domain core as large nebula filling viewport
- All domain entities orbiting, sized by sqrt(source_count)
- Ghost domains as dim attractors evenly distributed around circle (gravitational pull)
- Entity positions: rank-based radius (important near core) + pull toward other domains for bridge entities
- Top 30% always labeled, rest on hover
- Known issue: entity band distribution still needs tuning

### Star View (`/viz/star?entity=ID`, accent: teal)
- Central entity as bright star
- Inner ring: documents mentioning this entity
- Outer ring: co-occurring entities positioned near their shared docs
- 2-hop graph: entity ↔ doc ↔ co-entity (no direct entity↔entity lines)
- API: `GET /entities/{id}/star-graph` returns full 2-hop graph in one call
- Click doc → opens ReaderPane in left panel with entity highlights
- Double-click entity (sidebar or inline text) → navigates star view to that entity
- Click co-entity → reloads star view centered on that entity
- Search cascade: docs flash (shuffled, top 10) → pulses → center → pulses → co-entities
- Domain-type entities filtered from co-entity ring

### Color Accents by View
Each view has a distinct color accent to help orientation:
- Galaxy: blue/cyan (`rgba(100,180,255,...)`)
- Sector: amber (`rgba(200,120,80,...)`)
- System: purple (`rgba(160,130,200,...)`)
- Star: teal (`rgba(100,200,180,...)`)

## What NOT to Change

### The postMessage contract
Both the old viz (`cosmic-viz.html`) and new viz (`viz/index.html`) use the same postMessage types:
- `{type: 'node_selected', nodeType: 'entity'|'domain'|'trade_route', data: {...}}`
- `{type: 'node_cleared'}`
- `{type: 'search_result', entities: [...]}`

The parent page (`viz/page.tsx`) listens for `node_selected`/`node_cleared` from the iframe, and forwards `search_result` TO the iframe. Don't break this contract — the galaxy panel depends on it.

### The search response shape
```json
{
  "query": "...",
  "entities": [{"id", "name", "type", "score", "source_count", "paths", "appearances"}],
  "chunks": [{"chunk_id", "text", "document_id", "document_title", "score", "entity_overlap"}],
  "sub_queries_used": [...],
  "total_entities": N,
  "total_chunks": N
}
```
The MCP server, frontend search bar, WebSocket broadcast, and galaxy glow all depend on this shape.

### The /graph response shape
The viz (both old and new) consumes this. Key fields:
- `domain_positions` — path → {x, y} (0-1 UMAP coords)
- `domain_video_counts` — path → count (badly named, it's doc counts)
- `domain_specs` — path → {spec_version} or null
- `active_simmers` — list of domain paths currently simmering
- `region_colors` — path → hex color
- `entities` — [{entityId, name, type, videoCount, domainWeights}]
- `trade_routes` — [{source, target, weight}]

### Domain normalization cascade
When a new domain is proposed by the classifier, it goes through `normalize_domain_label()` which checks the merge map, then creates the domain if new. Don't skip this — it prevents duplicate domains.

### The three-tier entity normalization
1. Plural collapse (string rules)
2. Embedding similarity (all-MiniLM-L6-v2, threshold 0.85 auto-merge, 0.70-0.85 review queue)
3. Manual review (UI buttons on pipeline page)

Run via `POST /normalize` or automatically after batch extraction.

## Why Certain Design Choices Were Made

### Why entities are extracted with Haiku, not Sonnet
Cost. Haiku is 10x cheaper. The simmered extraction spec encodes the domain knowledge — Haiku just follows instructions. Validated in warhammer experiments: simmered Haiku beats generic Sonnet.

### Why classification uses Sonnet
Classification needs judgment — deciding what domain a document belongs to. Haiku was tested and produced worse taxonomy. The Sonnet call is fast (~2s) and only happens once per document.

### Why 2 judges instead of 3 for simmering
33% cheaper with marginal quality loss. Two judges still produce meaningful disagreement for synthesis. The judges are: "Coverage & Depth" and "Precision & Quality".

### Why co-occurrence edges only (no typed relationships)
Typed edges (uses, works_at, etc.) add error surface without proven retrieval benefit at our scale. Co-occurrence gets 80% of retrieval value for zero LLM cost. Typed edges are a documented V2 upgrade.

### Why the galaxy viz uses world space 5000x5000
Enough room for 100+ domains with minimum separation (400wu). The camera at zoom 0.18 sees the full galaxy. Zoom to 2.0+ for entity-level detail. The world doesn't resize — new domains just fill more of it.

### Why entity positions use cubed domain weights
With 4 domains and roughly equal weights (0.25 each), entities sat in the center (forces cancel). Cubing the weights breaks symmetry — an entity at 0.4/0.3/0.3 effectively pulls 0.064/0.027/0.027, making the dominant domain 2.4x stronger.

## File Locations Quick Reference

```
orchestrator/src/
  main.py              — FastAPI app, all routes registered
  config.py            — Settings from env vars (AWS, Bedrock, thresholds)
  db.py                — SQLite schema + WAL init (14 tables)
  broadcast.py         — WebSocket broadcaster class
  mcp_server.py        — MCP stdio server (5 tools)
  routes/              — All API endpoints
  pipeline/
    chunker.py         — Document chunking with overlap
    classifier.py      — Sonnet domain classification
    domain_normalizer.py — Domain merge map + creation
    excerpt.py         — Classification excerpt builder
    extractor.py       — Haiku entity extraction
    normalizer.py      — Entity merge map + exact match
    cooccurrence.py    — Statistical co-occurrence edges
    embedding_normalizer.py — Three-tier normalization cascade
    subdomain_discovery.py — Cheap Sonnet call for subdomains
    search/            — 5-stage search pipeline (6 modules)

worker/src/
  main.py              — Poll loop + job dispatch
  db.py                — Same as orchestrator (copied)
  config.py            — Same as orchestrator (copied)
  normalizer.py        — Same as orchestrator embedding_normalizer (copied)
  jobs/
    runner.py          — Pick/mark jobs
    simmer_general.py  — General spec simmering + iteration recording
    simmer_domain.py   — Domain-specific simmering
    extract_batch.py   — Batch extraction + normalization

frontend/
  src/app/
    page.tsx           — Upload page
    pipeline/page.tsx  — Pipeline dashboard
    entities/page.tsx  — Entity list
    entities/[id]/page.tsx — Entity detail with snippets
    viz/page.tsx           — Galaxy viz (iframe + panel + search bar + WebSocket)
    viz/sector/page.tsx    — Sector viz (domain cluster detail, amber accent)
    viz/system/page.tsx    — System viz (single domain + orbiting entities, purple accent)
    viz/star/page.tsx      — Star viz (entity 2-hop graph + ReaderPane panel, teal accent)
    simmer/[id]/page.tsx   — Simmer progress with trajectory chart
    extraction/[id]/page.tsx — Batch extraction results + document reader
  src/components/
    galaxy/            — GalaxyPanel, entity/domain/trade route panels, nav trail
    reader/            — Document reader with entity highlights (onNavigateEntity for star view)
    simmer/            — Simmer header, phase tabs, iteration list, criterion cards
    extraction/        — Extraction header, stat strip, doc list, entity panel
  public/
    cosmic-viz.html    — Old v1 galaxy viz (self-contained, still works)
    viz/               — New v2 galaxy viz (modular ES modules)
      index.html       — Galaxy view entry point (zoom < 0.35)
      sector.html      — Sector view entry point (?domain=path or ?cluster=N)
      system.html      — System view entry point (?domain=path, auto-picks if empty)
      star.html         — Star view entry point (?entity=ID)
      core/            — camera.js, state.js, utils.js (shared across all views)
      renderers/
        galaxy.js      — Cluster clouds, domain nebulae, trade routes, entity stars
        sector.js      — Sector domain nebulae, weighted routes, key entities, edge domains
        system.js      — Domain core nebula, orbiting entity stars with type colors
        star.js        — Central star, document nodes, co-entity nodes, 2-hop connections

docs/
  ARCHITECTURE.md      — Full system architecture reference
  IMPLEMENTATION-NOTES.md — This file
  orchestrator/        — Design spec, implementation plan, search specs
  design/              — UI/viz design specs from design agent
  search/              — Search system documentation
  cosmic-visualization/ — Viz rendering specs
```
