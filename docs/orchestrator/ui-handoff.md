# UI Design Handoff — Noospheric Orrery

**Date:** 2026-03-27
**Purpose:** Everything a UI/design agent needs to brainstorm the frontend redesign.

## What This App Does

An adaptive knowledge graph extraction pipeline. Users upload documents (meeting notes, transcripts, articles). The system:
1. **Classifies** docs into a domain taxonomy (Sonnet via Bedrock)
2. **Simmers** an extraction spec tailored to the corpus (simmer-sdk iterative refinement)
3. **Extracts** entities from all docs (Haiku via Bedrock)
4. **Normalizes** entities (plural collapse → embedding similarity → manual review)
5. **Discovers subdomains** as the taxonomy deepens
6. **Visualizes** the knowledge graph as a cosmic galaxy map

## Current Pages

### Upload (`/`)
- Drag-and-drop file zone
- Directory path input
- Per-file status after upload (classified, extracted, domains assigned)

### Pipeline (`/pipeline`)
- Stats bar: doc count, entity count, domain count, active jobs
- Active jobs display (running/queued with time-since)
- Domain tree (paginated, shows doc count + spec version, "simmer" button per domain)
- Normalization panel (merge history paginated, review queue with merge/skip buttons)

### Entities (`/entities`)
- Paginated table: name, type (color-coded badge), source count
- Type filter dropdown
- Click → detail page

### Entity Detail (`/entities/[id]`)
- Entity name, type badge, source count
- Merge history ("also known as" with strikethrough names)
- Source documents list

### Galaxy (`/viz`)
- Cosmic visualization (Canvas2D, 712-line self-contained HTML)
- Domains as nebulae, entities as stars, co-occurrence as trade routes
- Pan/zoom, LOD (nebulae only → stars → labels at deeper zoom)
- Colors per domain via HSL hash of path

## API Endpoints Available

```
GET  /health                    → {status: "ok"}
GET  /stats                     → {document_count, entity_count, domain_count, active_jobs}
POST /ingest                    → upload file, returns {document_id, title, domains, entity_count, jobs_queued}
POST /ingest/directory          → {path: "/local/dir"}, returns {documents: [...], total}
GET  /documents                 → [{id, title, status, created_at, domains, entity_count}]
GET  /documents/{id}            → full doc with domains and entities
GET  /domains                   → [{id, path, parent_path, document_count, spec_version}]
GET  /entities?type=X&domain=Y  → [{id, canonical_name, type, source_count}]
GET  /entities/{id}             → entity with sources and merge_history
GET  /jobs                      → [{id, type, target, status, created_at, started_at, completed_at}]
POST /simmer/{domain}           → trigger domain-specific simmering
POST /normalize                 → run 3-tier normalization, returns {plural_merges, embedding_merges, queued_for_review, before, after}
GET  /normalize/summary         → {merges_by_method, total_merges, pending_reviews, recent_merges}
GET  /normalize/review          → [{id, entity_a, entity_b, similarity}]
POST /normalize/review/{id}?action=merge|keep_separate
POST /discover-subdomains       → {docs_checked, subdomains_added, new_subdomains}
GET  /graph                     → cosmic_data_v4 format for visualization
```

## Data at Current Scale

- 20 documents (meeting notes from a startup)
- 260 entities across 7 types (Person, Organization, Location, Product, Technology, Event, Concept)
- 14 domains, 3 levels deep (e.g., `business/product_development/strategy/ecommerce`)
- ~90 co-occurrence trade routes
- 12 normalization merges (plural + embedding + manual review)

## Pipeline States & Lifecycle

A document goes through: `pending → classified → extracted → enriched`

A domain can be: no spec (just classified) → simmering → has spec (v1, v2...)

Jobs are: `queued → running → completed | failed`

The general extraction spec is simmered once on first ingest (~55 min). After that, new docs extract immediately (~seconds each). Domain-specific specs are triggered manually or at threshold.

## Current Tech Stack

- **Backend:** FastAPI (Python 3.11), SQLite WAL mode, Anthropic SDK (Bedrock)
- **Frontend:** Next.js 16, React 19, shadcn/ui, Tailwind 4
- **Viz:** Self-contained Canvas2D HTML (cosmic-viz.html embedded via iframe)
- **Theme:** Dark mode, monospace font, muted borders, colored accents

## What Needs Design Attention

### 1. Pipeline Execution View
Current: Stats bar + active jobs list. Want: Something that shows the pipeline stages (ingest → classify → simmer → extract → normalize) with real execution state — which stage each doc is in, progress of simmering iterations, timing. Think Airflow DAG view but fitting the dark/minimal aesthetic. The simmer loop has iteration data available (trajectory with scores per iteration).

### 2. Simmer Progress Visualization
The simmering process generates trajectory data:
```json
{"iteration": 0, "coverage": 6, "precision": 4, "taxonomy_quality": 5, "composite": 5.0, "key_change": "seed"}
{"iteration": 1, "coverage": 6, "precision": 5, "taxonomy_quality": 5.5, "composite": 5.5, "key_change": "Split Thing into Product+Technology"}
```
This should be visualized — iterations as a timeline, scores as a chart, key changes as annotations. Eventually with a space/cosmic theme (star forming, brightness = score).

### 3. Upload Experience
Current: Basic drag-and-drop + directory path. Could be better — show real-time classification as files process, domain assignment animation, progress toward simmering threshold.

### 4. Entity Explorer
Current: Flat paginated table. Could show entity clusters, type distribution, relationships. The co-occurrence data is available via the graph endpoint.

### 5. Galaxy Integration
Currently in an iframe. Could be more integrated — clicking a domain nebula could filter the entity table, clicking a star could open the entity detail, etc.

### 6. Overall Aesthetic
User wants: dark, minimal, monospace, muted colors with bright accents. Think terminal/dashboard hybrid. The cosmic viz sets the vibe — the admin pages should feel like the same product, not a different app. Readable text is important (the viz intentionally sacrifices readability for aesthetics, the dashboard shouldn't).

## Design Constraints

- Must work with existing API — no backend changes needed for UI redesign
- shadcn/ui components are available (button, card, badge, input, table, tabs)
- Tailwind 4 for styling
- Dark mode only (no light mode toggle needed)
- Monospace font (Courier New or similar)
- Data refreshes every 5 seconds on the pipeline page

## Reference Material

- Cosmic viz rendering spec: `docs/cosmic-visualization/README.md`
- Orchestrator design spec: `docs/orchestrator/design.md`
- The existing cosmic viz: `frontend/public/cosmic-viz.html` (712 lines, all the visual language)
- User's vision note: wants simmering visualized like "Airflow meets cosmic viz"
