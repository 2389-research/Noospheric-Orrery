# Galaxy Interaction Layer — Implementation Spec

## Scope and philosophy

**What this spec covers:** A new information panel that lives in the parent page alongside the galaxy iframe, plus simplified tooltip behavior inside the viz itself.

**What this spec does not touch:** Canvas2D rendering, physics simulation, LOD system, star/nebula/route visual styling, zoom behavior, or any existing viz code beyond one small addition to the click handler.

**The core principle:** Tooltip and panel are doing different jobs and must not duplicate content.

- **Tooltip** = identification and triage. "What is this, should I click it?" Answers in under a second, disappears on mouseleave. Two lines maximum.
- **Panel** = exploration. "I clicked, tell me everything." Persistent, navigable, pulls threads.

The tooltip teases. The panel delivers.

---

## Architecture

The viz is a self-contained iframe. The panel lives in the parent React page. They communicate via `postMessage`.

```
Parent page
┌─────────────────────────────────────────┬────────────────┐
│                                         │                │
│   <iframe src="/cosmic-viz.html">       │  GalaxyPanel   │
│   [canvas — unchanged]                  │  (new)         │
│   [tooltip — simplified]                │                │
│                                         │                │
└─────────────────────────────────────────┴────────────────┘
         │  postMessage                     │
         └──────────────────────────────────┘
```

**Panel width:** 300px fixed, right of iframe. Iframe shrinks to fill remaining width. On the existing `/viz` page this means the iframe goes from full-width to `calc(100% - 300px)`. The panel only renders when a node is pinned — it does not occupy space when nothing is selected (or collapses to a minimal "click a star" empty state).

---

## Part 1 — postMessage bridge (viz change)

This is the only modification to `cosmic-viz.html`. In the existing pin/click handler, after the visual pin state is set, add:

```javascript
// After existing pin logic:
if (pinnedNode) {
  window.parent.postMessage({
    type: 'node_selected',
    nodeType: pinnedNode.nodeType,  // 'entity' | 'domain' | 'trade_route'
    data: buildNodePayload(pinnedNode)
  }, '*');
} else {
  window.parent.postMessage({ type: 'node_cleared' }, '*');
}

function buildNodePayload(node) {
  if (node.nodeType === 'entity') {
    return {
      id: node.id,
      name: node.label,
      type: node.type,           // Person, Organization, etc.
      source_count: node.videoCount,
      domain_weights: node.domainWeights,  // already on the node
    };
  }
  if (node.nodeType === 'domain') {
    return {
      path: node.path,
      document_count: node.documentCount,
    };
  }
  if (node.nodeType === 'trade_route') {
    return {
      source: node.source,
      target: node.target,
      weight: node.weight,
    };
  }
}
```

The parent listens:

```javascript
useEffect(() => {
  const handler = (e) => {
    if (e.data.type === 'node_selected') setSelectedNode(e.data);
    if (e.data.type === 'node_cleared') setSelectedNode(null);
  };
  window.addEventListener('message', handler);
  return () => window.removeEventListener('message', handler);
}, []);
```

**Clicking empty space** already unpins in the viz — the existing `node_cleared` message handles panel dismissal.

---

## Part 2 — Tooltip (simplified, inside viz)

Replace the current multi-line tooltip with a minimal two-line version. No snippets, no domain weights, no co-occurrence data — all of that moves to the panel.

### Entity tooltip
```
dylan richard
Person · 35 docs
```

### Domain tooltip
```
investor_meetings
19 docs · 84 entities
```

### Trade route tooltip
```
investor_meetings ↔ strategy
weight: 45
```

### Implementation notes
- Same DOM element and positioning logic as current tooltip — just strip the content
- Same `rgba(6,13,34,0.95)` background, `1px solid rgba(100,180,255,0.15)` border, Courier New font
- Name: 13px, `#e8eaf0`
- Sub line: 11px, `rgba(100,180,255,0.45)`
- Padding: 8px 11px
- Keep appearing on hover, disappearing on mouseleave — behavior unchanged
- The tooltip's continued existence serves one purpose beyond information: it signals to the user that nodes are interactive. Do not remove it entirely.

---

## Part 3 — GalaxyPanel component

### File location
`frontend/components/GalaxyPanel.tsx` (or equivalent)

Used on `/viz` page, rendered to the right of the iframe, receives `selectedNode` state from parent.

### Component hierarchy
```
GalaxyPanel
├── PanelTabs (entity / domain / route — only shown when relevant)
├── NavTrail
├── PanelBody
│   ├── EntityPanel
│   ├── DomainPanel
│   └── TradeRoutePanel
└── PanelFooter
```

---

## EntityPanel

Rendered when `nodeType === 'entity'`.

### Data fetched on mount (when entity id is available)
```
GET /entities/{id}
→ merge_history, sources (for doc count)

GET /documents — filter to docs containing this entity
→ for snippet fetching

reader endpoint per source doc (lazy, loads after paint)
→ snippets
```

Entity id is not in the postMessage payload initially — resolve from `canonical_name` by matching against the entities list, or add `entity_id` to the viz node data (preferred — ask orrery agent).

### Layout

```
┌─────────────────────────────────────┐
│ Person                              │  ← 9px type label, entity color
│ dylan richard                       │  ← 18px name
│ 35 docs across corpus               │  ← 11px muted
│                                     │
│ DOMAIN PRESENCE                     │  ← section label
│ [donut ring]  investor_meetings 33% │  ← ring + weight list
│               strategy         39%  │
│               team_meetings    13%  │
│               vc_firms         15%  │
│                                     │
│ FROM THE DOCS                       │
│ ┌─────────────────────────────────┐ │  ← snippet, border-left accent
│ │ The Betaworks meeting, attended │ │
│ │ by Harper Reed and Dylan...     │ │
│ └─────────────────────────────────┘ │
│ ┌─────────────────────────────────┐ │
│ │ Dylan Richard mentioned...      │ │
│ └─────────────────────────────────┘ │
│                                     │
│ OFTEN APPEARS WITH                  │
│ [harper reed] [betaworks] [series b]│  ← clickable chips
│                                     │
│ ALSO KNOWN AS                       │  ← only if merge_history non-empty
│ dylan  d. richard                   │  ← strikethrough style
├─────────────────────────────────────┤
│ [↗ open entity]  [⊞ filter docs]   │  ← footer actions
└─────────────────────────────────────┘
```

### Domain weight ring

SVG donut, ~72px diameter. One arc segment per domain in `domain_weights`, proportional to weight value. Arc color = domain's `region_color` from the graph data (already available in parent page from `GET /graph`). Small gap between segments (1.5% of circumference) for readability.

Each weight row in the list beside the ring is clickable — clicking navigates the panel to that domain (pushes to nav trail, renders DomainPanel).

### Snippets

Load lazily after entity data resolves. While loading show pulsing placeholder text: "loading mentions…" in tertiary color. Show max 2 snippets. Entity name bolded/highlighted within snippet text. Snippets are cached on the entity node after first load — don't re-fetch on re-select.

### Co-occurrence chips

Derived from `trade_routes` in the graph data — entities that share trade routes with this entity's primary domain, filtered to entities that actually co-occur in the same documents. Each chip is colored by entity type. Clicking a chip navigates the panel to that entity (pushes trail).

### Merge history

Shown only if `entity.merge_history` is non-empty. Strikethrough style on the old names. No interaction needed — it's a curiosity/confidence signal.

### Footer actions
- `↗ open entity` → navigates to `/entities/{id}` (full entity detail page)
- `⊞ filter docs` → navigates to `/extraction/{last_job_id}?entity={id}` (batch view filtered to this entity)

---

## DomainPanel

Rendered when `nodeType === 'domain'`.

### Data fetched on mount
```
GET /domains → find domain by path, get spec_version
GET /entities?domain={path} → top entities
GET /jobs?target={path}&type=simmer_domain → last simmer job for spec status
```

### Layout

```
┌─────────────────────────────────────┐
│ Domain                              │  ← 9px label
│ investor_meetings                   │  ← 18px, domain color
│ business / fundraising              │  ← full path, muted
│                                     │
│ [19 docs]  [84 entities]  [6 routes]│  ← stat strip
│                                     │
│ ● spec v2 · simmered 3 days ago     │  ← green if spec exists
│ ○ no spec · simmer to extract       │  ← amber if no spec
│                                     │
│ TOP ENTITIES BY MENTION             │
│ harper reed    [████████░] 19       │  ← bar proportional to count
│ dylan richard  [██████░░░] 14       │     clickable → entity panel
│ james higa     [████░░░░░] 11       │
│ betaworks      [███░░░░░░]  9       │
│ series b       [██░░░░░░░]  7       │
├─────────────────────────────────────┤
│ [↗ view docs]    [⟳ re-simmer]      │
└─────────────────────────────────────┘
```

### Spec status badge
- Spec exists: green dot + "spec v{N} · simmered {relative time}"
- No spec: amber dot + "no spec · simmer to extract"
- Currently simmering: pulsing amber dot + "simmering now…" — link to `/simmer/{job_id}`

### Top entities list
- Show top 5 by `source_count` within this domain
- Bar width proportional to count relative to max in list
- Bar color = entity type color
- Each row clickable → navigates to EntityPanel for that entity (pushes trail)

### Footer actions
- `↗ view docs` → navigates to `/documents?domain={path}`
- `⟳ re-simmer` → calls `POST /simmer/{domain}` then navigates to `/simmer/{new_job_id}`

---

## TradeRoutePanel

Rendered when `nodeType === 'trade_route'`.

### Data fetched on mount
```
GET /entities?domain={source} and GET /entities?domain={target}
→ intersect the two sets to find shared entities
```

This is a client-side intersection — no new endpoint needed. Shared entities = entities that appear in both domain entity lists.

### Layout

```
┌─────────────────────────────────────┐
│ Trade Route                         │  ← 9px label
│ weight: 45 · strong connection      │  ← cyan accent color
│                                     │
│ ┌──────────────┐   ┌──────────────┐ │
│ │investor_mtgs │ ↔ │  strategy    │ │  ← each end clickable
│ │   19 docs    │   │   20 docs    │ │     → navigates to DomainPanel
│ └──────────────┘   └──────────────┘ │
│                                     │
│ SHARED ENTITIES                     │
│ ● harper reed        12 docs        │  ← color dot = entity type
│ ● dylan richard       9 docs        │     clickable → EntityPanel
│ ● series b            7 docs        │
│ ● betaworks           5 docs        │
│ ● product-market fit  3 docs        │
├─────────────────────────────────────┤
│ [⊞ filter to both domains]          │
└─────────────────────────────────────┘
```

### Connection strength label
Derived from weight:
- weight ≥ 40 → "strong connection"
- weight 15–39 → "moderate connection"
- weight < 15 → "weak connection"

### Shared entities
Sorted by `source_count` descending. Show max 8. Each row clickable → EntityPanel for that entity. Color dot = entity type color.

### Footer action
- `⊞ filter to both` → navigates to entity grid filtered to entities in both domains. This requires a URL scheme like `/entities?domain[]={source}&domain[]={target}&intersect=true` — confirm with orrery agent whether that filter is supported or needs adding.

---

## NavTrail

Appears below the tab row, above the panel body. Shows navigation history within the current panel session.

```
dylan richard › betaworks › investor_meetings
```

- Max 3 items shown (older history is dropped)
- Each past item is clickable — navigates back to that state
- Current item (rightmost) is not clickable, slightly brighter
- Resets when panel is dismissed (node_cleared) and on page navigation
- Items are stored as `{name, nodeType, id}` — clicking re-renders the appropriate panel

---

## Panel empty / loading states

**Nothing selected (panel collapsed):**
Panel is not rendered — iframe takes full width. A faint hint text can optionally appear at the bottom of the viz: "click any star or nebula to explore" — but this is in-viz territory, treat as optional.

**Panel loading (postMessage received, data fetching):**
Panel renders immediately with the data from the postMessage payload (name, type, count). Sections that require API fetches show skeleton placeholders. Snippets show "loading mentions…" pulse. This means the panel feels instant on click — the primary content is there immediately, secondary content loads in.

**API fetch failure:**
Show "couldn't load details" in the affected section with a small retry link. Do not fail the whole panel.

---

## Visual style

The panel must feel like it belongs to the same product as the viz, not like a React component dropped next to a canvas. Use the cosmic aesthetic:

```
Background:        rgba(6, 13, 34, 0.97)     ← matches viz tooltip bg
Border (left):     1px solid rgba(100,180,255,0.12)
Section labels:    9px, rgba(100,180,255,0.4), uppercase, letter-spacing .08em
Primary text:      #e8eaf0
Secondary text:    rgba(180,195,220,0.65)
Muted text:        rgba(100,180,255,0.4)
Accent color:      rgba(100,180,255,1.0)      ← info/interactive elements
Font:              'Courier New', monospace   ← matches viz labels
```

Entity type colors (same as viz — do not use CSS variables for these, they must match exactly):
```
Person:       #7F77DD
Organization: #378ADD
Product:      #1D9E75
Technology:   #BA7517
Event:        #D85A30
Concept:      #9c9a92
Location:     #5DCAA5
```

Borders between sections: `1px solid rgba(100,180,255,0.08)` — very subtle.

Scrollbar: 3px width, `rgba(100,180,255,0.2)` thumb, transparent track.

---

## Questions for orrery agent

Before implementation, confirm:

1. **Entity ID in postMessage** — the viz nodes have `name` but the panel needs `entity_id` to call `GET /entities/{id}`. Is `id` already on the node object in the viz, or does it need to be added when the graph data is loaded?

2. **Domain entity list** — does `GET /entities?domain={path}` return entities for exactly that domain path, or does it include subdomain entities? The trade route shared-entity intersection depends on this behavior.

3. **Multi-domain entity filter** — does `/entities?domain[]=A&domain[]=B&intersect=true` need to be added, or is there another way to express "entities in both domains"?

4. **Co-occurrence data for chips** — the "often appears with" chips need entity-level co-occurrence, not just domain-level trade routes. Is this derivable from the graph data (entities that share the same document sources), or does it need a new endpoint like `GET /entities/{id}/cooccurrences`?

5. **Snippet caching** — the viz already caches snippets on the node after first hover load. Can the panel reuse that cache via the postMessage payload (include cached snippets in the message if available), or should the panel fetch independently?
