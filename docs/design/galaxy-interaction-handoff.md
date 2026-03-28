# Galaxy Visualization — Interaction Design Handoff

**Date:** 2026-03-28
**Purpose:** Current state of the galaxy viz + what data is available, so the design agent can spec hover/click/pin behaviors.

## Current Implementation

Self-contained Canvas2D viz at `frontend/public/cosmic-viz.html`, embedded via iframe at `/viz`. Fetches data from `GET /graph`.

### What's Rendered

| Visual | Data Source | Behavior |
|--------|-----------|----------|
| **Nebulae** (domains) | domain_positions, region_colors | Rotating gas layers, core glow, label below |
| **Stars** (entities) | entities array with domainWeights | Orbit around primary domain, size = source_count |
| **Trade routes** | trade_routes (cross-domain edges) | Dashed cyan lines with flowing particles |
| **Labels** | node.label | Domain labels always visible, entity labels on zoom/hover |

### Current Interaction States

**Hover (entity):**
- Entity label shows (bold 9px, entity color)
- Connected entities show labels (8px, entity color)
- Connected domains go white bold
- Unconnected nodes dim to 0.15 opacity
- Tooltip shows: type, name, doc count, domain weights, context snippets (fetched from reader API)

**Hover (domain):**
- Domain label goes white bold, nebula brightens 2x
- Its entities light up with labels
- Other domains/entities dim
- Tooltip shows: "DOMAIN", name, doc count

**Pin (click any node):**
- Locks the hover highlight — neighborhood stays visible
- Can hover other nodes while pinned (tooltip updates but highlight stays)
- Click same node to unpin, click empty space to unpin, click different node to switch pin

**No interaction:**
- All nodes at full opacity
- Domain labels at 0.9 alpha (colored)
- Entity labels only visible at zoom > 0.7

### Physics

- Entities attracted to domains proportional to `domainWeights` (squared for symmetry breaking)
- Slow tangential orbit around primary domain
- Local collision repulsion between nearby entities
- Velocity damping + speed cap

---

## Data Available via API

### `GET /graph` — what the viz currently consumes

```json
{
  "domain_positions": {"business/fundraising/investor_meetings": {"x": 0.5, "y": 0.18}},
  "domain_video_counts": {"business/fundraising/investor_meetings": 13},
  "region_colors": {"business/fundraising/investor_meetings": "#d9486e"},
  "subdomains": ["business/product_development/strategy/ai"],
  "entities": [
    {
      "name": "harper reed",
      "type": "Person",
      "videoCount": 44,
      "domainWeights": {
        "business/fundraising/investor_meetings": 0.34,
        "business/product_development/strategy": 0.377,
        "business/venture_capital/vc_firms": 0.179,
        "business/operations/team_meetings": 0.104
      }
    }
  ],
  "trade_routes": [
    {"source": "business/fundraising/investor_meetings", "target": "business/venture_capital/vc_firms", "weight": 45}
  ]
}
```

### `GET /entities/{id}` — entity detail (fetchable on demand)

```json
{
  "id": "67af4f94-...",
  "canonical_name": "harper reed",
  "type": "Person",
  "source_count": 44,
  "sources": [
    {"document_id": "abc...", "chunk_id": "def...", "extraction_pass": "general", "job_id": "ghi..."}
  ],
  "merge_history": ["harper"]
}
```

### `GET /documents/{id}/reader` — document with entity highlights (fetchable on demand)

```json
{
  "document": {"id": "...", "title": "Meeting with James Higa", "domains": [...]},
  "entities": [
    {
      "canonical_name": "harper reed",
      "type": "Person",
      "mention_count": 7,
      "positions": [0.1, 0.2, 0.45, 0.6, 0.7, 0.85, 0.95],
      "snippets": [
        "Harper Reed discussed the product roadmap for Q3...",
        "According to Harper Reed, the key metric is..."
      ]
    }
  ],
  "segments": [{"type": "text", "text": "..."}, {"type": "entity", "text": "Harper Reed", "entity_id": "...", "entity_type": "Person"}],
  "total_mentions": 40
}
```

### `GET /documents` — document list

```json
[
  {"id": "...", "title": "Meeting with James Higa", "status": "extracted", "domains": ["business/fundraising/investor_meetings", "business/product_development/strategy"], "entity_count": 97}
]
```

### `GET /jobs` — pipeline jobs with results

```json
[
  {"id": "...", "type": "simmer_domain", "target": "business/product_development/strategy", "status": "completed",
   "results": {"entities_found": 284, "entities_new": 31, "docs_processed": 24, "spec_version": "domain/strategy_v1"}}
]
```

### `GET /domains` — domain list

```json
[
  {"id": "...", "path": "business/fundraising/investor_meetings", "document_count": 19, "spec_version": 1}
]
```

---

## What Needs Design Decisions

### 1. Entity Hover — what to show

Currently: type, name, doc count, domain weight %, context snippets.

Open questions:
- Should the tooltip show which docs the entity appears in (titles)?
- Should it show merge history ("also known as: harper")?
- Should the snippets be collapsible or always shown?
- Max tooltip height? Currently unbounded with 3 snippets.

### 2. Entity Click/Pin — what to show

Currently: same as hover but locked. No panel or sidebar.

Options to consider:
- **Side panel** that slides in with full entity detail (like the entity detail page)?
- **Navigate** to `/entities/{id}` on click?
- **Inline expansion** — the tooltip becomes a larger card with more detail?
- **Keep current** — pin just locks the visual highlight, tooltip stays as-is?

### 3. Domain Hover — what to show

Currently: "DOMAIN", name, doc count. Very minimal.

Available data for tooltip:
- Doc count
- Spec version (has the domain been simmered?)
- Entity count (how many entities belong to this domain)
- Top entities by mention count
- Top entity types (distribution)
- Recent docs added

### 4. Domain Click/Pin — what to show

Currently: same as hover but locked.

Options:
- Show the domain's entity list?
- Navigate to domain-filtered entity page?
- Show domain spec info (simmer score, when it was created)?
- Show docs in this domain?

### 5. Trade Route Hover

Currently: no interaction on trade routes.

Available: `weight` (number of shared entities between the two domains).

Could show:
- Which entities are shared between the two domains
- Weight / strength of connection

### 6. Empty Space Click

Currently: unpins selection.

Could also:
- Show a mini dashboard (total stats)?
- Reset zoom?

---

## Current Visual Style

- Background: deep space navy (#01040a → #060d22 gradient)
- Domain nebulae: colored gas clouds, 4 rotating layers
- Entity stars: radial gradient core with aura
- Labels: Courier New monospace
- Tooltip: rgba(6,13,34,0.95) bg, 1px border rgba(100,180,255,0.15)
- Color per entity type: Person=#378ADD, Organization=#7F77DD, Product=#1D9E75, Technology=#BA7517, Event=#D85A30, Concept=#9c9a92, Location=#5DCAA5
- Domain colors: HSL hash of domain path, varied across spectrum

## Technical Constraints

- Canvas2D rendering at 60fps — no DOM elements inside the viz
- Tooltip is a DOM element positioned over the canvas
- Data fetches (reader endpoint, entity detail) take 100-500ms
- Snippets are cached on the node after first load
- The viz is a single HTML file embedded via iframe — any panels/sidebars would need to be either inside the iframe or communicated to the parent page via postMessage

## Scale

Current: 14 domains, ~260 entities, ~90 trade routes, 24 docs.
Expected at production: 100+ domains, 1000+ entities, 500+ trade routes.

At scale, the LOD system hides entities at low zoom and only shows labels on hover/zoom. Performance is fine up to ~2000 nodes in Canvas2D.
