# Noospheric Orrery — Galaxy Visualization North Star Spec

## Vision

The galaxy visualization is a spatial interface to the knowledge graph. It is not a dashboard. It is not a chart. It is a place you can go to understand your corpus — and over time, to watch it think.

At any zoom level the user should be able to read something true and interesting about their data without clicking. The visual encodes meaning, not decoration. Every glow, pulse, and orbit reflects a real property of the knowledge graph.

The experience has a discovery arc: land at galaxy view, see the shape of everything, zoom toward something interesting, fall into a neighborhood, follow a thread. Each level reveals what the previous level hinted at.

---

## Architecture overview

```
GALAXY VIEW      zoom < 0.35
  Unit: cluster (emergent group of UMAP-proximate domains)
  Shows: shape of corpus, domain development, ambient activity
  Interaction: hover cluster → summary, click → fly to sector

SECTOR VIEW      zoom 0.35 – 0.75
  Unit: domain
  Shows: domain relationships, trade routes, key entities, activity
  Interaction: hover domain → detail, click entity → fly to star

SYSTEM VIEW      zoom 0.75 – 1.5
  Unit: entity
  Shows: entities orbiting domain, sizes by importance
  Interaction: hover entity → detail, click → fly to star view

STAR VIEW        zoom > 1.5
  Unit: document + local graph
  Shows: 2-hop neighborhood — docs, co-entities, connections
  Interaction: hover node → tooltip, click entity → re-center
```

Each zoom level has its own rendering mode. The transition between levels cross-fades over ~60 frames — nodes don't pop in, they materialize.

---

## World space

All positions live in world space, not canvas space. The canvas is a viewport into world space.

```javascript
const WORLD_W = 5000;  // world units
const WORLD_H = 5000;

// UMAP coordinates (0-1) → world space
domain.worldX = domain.umapX * WORLD_W;
domain.worldY = domain.umapY * WORLD_H;

// Minimum domain separation — enforced at init via repulsion pass
const MIN_DOMAIN_DIST = 400; // world units
```

Run 200 iterations of domain-only repulsion at load time to enforce minimum separation while preserving UMAP topology. Domains are then fixed — they never move during the session.

Entity positions are derived from domain weights (see Phase 2). They drift slowly but never teleport.

---

## Phase 1 — Galaxy View

### Goal
Show the shape of the entire corpus. Which areas are developed, which are dark. Make ambient activity visible as a slow atmospheric phenomenon. Give the user a reason to zoom in.

### What renders

**Cluster composite nebulae**

Clusters are emergent — computed at load time by grouping UMAP-proximate domains (within threshold distance). No manual cluster definitions.

```javascript
function computeClusters(domains, threshold = 600) {
  // Simple proximity grouping
  const clusters = [];
  const assigned = new Set();
  domains.forEach((d, i) => {
    if (assigned.has(i)) return;
    const cluster = [i];
    assigned.add(i);
    domains.forEach((other, j) => {
      if (assigned.has(j)) return;
      const dx = d.worldX - other.worldX;
      const dy = d.worldY - other.worldY;
      if (Math.sqrt(dx*dx + dy*dy) < threshold) {
        cluster.push(j);
        assigned.add(j);
      }
    });
    clusters.push(cluster);
  });
  return clusters;
}
```

Each cluster renders as a soft composite nebula — the sum of its domain glows at very low alpha, producing a faint cloud region. Individual domain nebulae within it are visible as brighter concentrations within the composite.

**Domain nebulae** (per domain, inside cluster cloud)

Three visual states — see nebula rendering spec (domain_nebula_spec.md):
- `maturity === 0` → wispy diffuse cloud, no core
- `simmering` → amber flickering protostar, bipolar jets
- `maturity > 0` → formed star, brightness and spike length encode maturity

Maturity = function of own spec + subdomain coverage (see domain_nebula_spec.md).

**Trade routes** (at galaxy view)

Very faint threads between cluster centroids only — not individual domains. Weight encoded in opacity. Mostly invisible until activity fires along them.

**Ambient activity**

Three activity signals visible at galaxy view:

1. **Cluster brightness** — clusters that have had recent search activity glow slightly warmer. Decays over ~3 minutes. Accumulates with repeated hits.

2. **Domain pulse** — when a domain spec is invoked (extraction, search), a soft bloom expands from that domain's position within its cluster. Not a sharp flash — a 1.5s radial gradient expansion at low alpha.

3. **Cross-cluster route shimmer** — when activity crosses cluster boundaries, the inter-cluster thread briefly brightens and carries a traveling dot. Identical mechanic to sector trade route pulses but smaller and dimmer.

### Layout

```
┌─────────────────────────────────────────────────────────┐
│                    ·  ·   ·                             │
│      [VC cluster]      [Content cluster]  ·             │
│    soft red-pink glow   purple glow                     │
│                                                         │
│         ·    [AI/Tech cluster]                          │
│              blue-teal glow                             │
│                                                         │
│   [Strategy cluster]        ·    [Ops cluster]          │
│    green glow                     green-yellow          │
│                                                         │
│  ·           ·        ·                    ·            │
└─────────────────────────────────────────────────────────┘
```

### Interaction

**Hover cluster:**
```
┌─────────────────────────┐
│ VC / FUNDING            │
│ 4 domains · 3 specs     │
│ 180 entities            │
│ last activity: 2m ago   │
│ ● 2 domains active      │
└─────────────────────────┘
```

**Click cluster** → camera flies to sector view of that cluster. Ease-in-out over 800ms. The cluster expands to fill the viewport as individual domain nebulae resolve.

**Click empty space** → unpin selection.

### Activity cascade at galaxy view

```
search hits entity in investor_meetings
  → investor_meetings domain pulses (soft bloom, 1.5s)
  → VC cluster brightens slightly (persistent, slow decay)
  → if route exists to strategy cluster: thread briefly shimmers
```

---

## Phase 2 — Sector View

### Goal
Show the relationships between domains within a cluster. Make trade routes legible. Reveal the key entities that bridge domains. Show which domains are developed vs unexplored. Activity is now specific — you can see which domain was hit, which route carried the signal.

### What renders

**Domain nebulae** — full nebula rendering (same as galaxy but much larger in viewport). Three states visible: unformed, simmering, formed. Core star size and spike length encode maturity.

**Trade routes** — visible as dashed cyan lines. Weight encoded in line thickness and opacity. Weight label on routes with weight ≥ 20. Direction of recent pulse shown by traveling dot.

**Key entities** — the top N entities by source_count for this sector become visible as small stars. Not labeled by default, labeled on hover. Bridge entities (multi-domain) float in the interstitial space between their domains.

**Edge domains** — domains from adjacent clusters visible at canvas edges as dim uninteractive clouds, giving spatial context.

**Domain labels + metadata** visible without hover:
```
investor_meetings
spec v2 · 19 docs · 84 entities
```

### Layout

```
┌─────────────────────────────────────────────────────────┐
│   [pre_seed]                    [seed_round]            │
│    ·  ★ ·                        ·  ·                  │
│                ╌╌╌╌╌╌╌╌╌╌╌╌╌                           │
│  [investor_meetings]  ●───────[vc_firms]                │
│    ★ ★ ★ ★ ★        45 shared  ★ ★ ★                  │
│           ★                  ★                          │
│              ★ [series b] ★   ← bridge entity           │
│           ★       ★                                     │
│  [strategy]              [founder_connections]          │
│  (edge, dim)              (edge, dim)                   │
└─────────────────────────────────────────────────────────┘
```

### Interaction

**Hover domain nebula:**
```
┌────────────────────────────────┐
│ investor_meetings              │
│ 19 docs · 84 entities          │
│ spec v2 · simmered 3 days ago  │
│ ● extraction enabled           │
│ ● 3 entities active right now  │
└────────────────────────────────┘
```

**Hover trade route:**
```
┌──────────────────────────────────┐
│ investor_meetings ↔ vc_firms     │
│ weight: 45 · strong connection   │
│ 15 entities shared               │
│ harper reed · series b · dylan…  │
└──────────────────────────────────┘
```

**Hover bridge entity** → tooltip with name, type, domain split.

**Click domain** → fly to system view of that domain.

**Click bridge entity** → fly to star view centered on that entity.

### Activity cascade at sector view

```
search hits entities in investor_meetings and vc_firms
  → both domain nebulae brighten (activity ring expands)
  → route between them carries traveling pulse dot
  → hit entities light up as small star flashes
  → if query used a bridge entity: that star flashes brighter
```

Activity is now legible as specific events — you can see exactly which domains were touched and which connection carried the signal.

---

## Phase 3 — System View

### Goal
Show the entity population of a single domain. Which entities are important, which are marginal. How entities cluster within the domain. The orbital physics makes it feel alive. Activity shows which entities are being used.

### What renders

**Domain core** — the domain nebula fills much of the viewport. The formed star (if spec exists) is visible and large at center. The cloud layers rotate slowly.

**Entity stars** — all entities for this domain rendered as stars orbiting the core. Size = `2 + Math.sqrt(source_count) * 0.9` (log-ish scaling). Color = entity type color. Bridge entities (multi-domain) have a faint halo ring and orbit at larger radius.

**Entity labels** — visible for entities above a source_count threshold. All others labeled on hover only. Threshold = top 30% by source_count.

**Orbital physics** — entities have fixed equilibrium positions from domain weights (cubed, see physics spec). They drift around their equilibrium in slow ellipses (see physics spec). Period 3-7 minutes.

### Layout

```
                    [concept]  ·
        [person]  ★               ★ [product]
    ★                                        ★
  [person]      ★     ★ [person]
           ★              ★
★                [DOMAIN CORE]                 ★
    [tech]  ★         ★        ★  [product]
               ★           ★
        [event]    ★ ·           [org]
    ★                     ★  [bridge ◎]
                ★
```

### Interaction

**Hover entity** → tooltip: name, type, source_count, domains.

**Click entity** → fly to star view centered on that entity.

**Click domain core** → fly back to sector view.

### Activity cascade at system view

```
search hits harper reed
  → harper reed star pulses bright (sine-curve flash, 1.4s)
  → nearby co-occurring entities briefly brighten
  → orbital trails briefly glow (show recent path)
  → domain core pulses once
```

At high query frequency, frequently-hit entities accumulate a residual glow — slightly warmer than idle entities. This is the heat map emerging naturally from repeated hits without any new mechanics.

---

## Phase 4 — Star View

### Goal
Show the 2-hop local graph around a single entity — its documents and the entities within those documents. This is the most granular spatial view before the text reader. The user is inside the entity's solar system.

### What renders

**Center entity** — large, bright, pulsing gently. Diffraction spikes. Name and type label below.

**Hop-1 documents** — orbit center at radius ~155 world units. Size = `6 + sqrt(entity_count) * 0.8`. Color = domain color blend (multi-domain docs have split halo + white ring indicator). Labeled with filename.

**Hop-1 entities** — co-occurring entities in center's documents. Orbit at radius ~232. Colored by entity type. Labeled. These are the entities the center entity "lives with" in its documents.

**Hop-2 documents** — documents containing hop-1 entities (not the center entity's direct docs). Radius ~325. Dim — 30% brightness of hop-1. Label on hover only.

**Hop-2 entities** — entities in hop-2 docs. Radius ~398. Very dim — 15% brightness. Label on hover only.

**Connection lines:**
- Center → hop-1 docs: faint, always visible
- Hop-1 docs → hop-1 entities: very faint, show co-occurrence structure
- Hop-1 entities → hop-2 docs: barely visible, peripheral context

### Layout

```
     ·  ·[h2e]·  ·[h2d]  ·  [h2e]·
  [h2d]    [h1e]──────[h1d]     [h2d]
      \       \       /    \
  [h2e] [h1e]  [CENTER]  [h1d]──[h1e]
      /       /       \    /
  [h2d]    [h1e]──────[h1d]     [h2d]
     ·  ·[h2e]·  ·[h2d]  ·  [h2e]·
```

### Multi-domain documents at star view

A document assigned to `investor_meetings` AND `strategy` renders with:
- Color = blend of both domain colors
- White orbital ring (visual indicator of multi-domain status)
- Second color halo at lower alpha behind the main glow
- Tooltip shows both domain names

It floats in the same orbit as single-domain docs — the multi-domain nature is encoded in appearance, not position.

### Interaction

**Hover hop-1 doc** → tooltip: filename, entity count, domains, multi-domain indicator.

**Hover hop-1 entity** → tooltip: name, type, "click to re-center".

**Hover hop-2 nodes** → label appears, minimal tooltip.

**Click hop-1 entity** → re-center star view on that entity. The constellation rebuilds around the new center. Previous center appears in the outer ring as a hop-1 entity of the new center.

**Double-click document** → open document reader (the highlighted text view).

**Click center** → fly back up to system view.

### Activity cascade at star view

```
search hits this entity (center)
  → center pulses bright, rings expand outward
  → connection lines briefly glow
  → hit documents flash (if specific docs were retrieved)
  → their co-entities briefly brighten

search hits a hop-1 entity
  → that entity star flashes
  → connecting documents briefly brighten
  → center receives a secondary pulse (dimmer)

search hits a hop-2 entity
  → faint flash at outer ring
  → connecting hop-2 doc brightens briefly
  → ripples inward toward hop-1 (very faint)
```

---

## Activity system — unified spec

### postMessage contract

Parent page → viz iframe:

```javascript
iframe.contentWindow.postMessage({
  type: 'search_result',
  entities: ['harper reed', 'dylan richard'],  // canonical names
  documents: ['doc-abc123'],                    // optional
  routes: [                                     // optional
    ['business/strategy', 'business/fundraising']
  ]
}, '*');
```

### Activity state per node

```javascript
// Added to every entity, domain, document node:
node.activityGlow = 0;      // 0-1, drives brightness boost
node.activityDecay = 0.0012; // per ms — tune per zoom level

// Each frame:
node.activityGlow = Math.max(0, node.activityGlow - node.activityDecay * dt);
```

### Brightness boost from activity

```javascript
const boost = 1 + node.activityGlow * BOOST_SCALE;
// BOOST_SCALE per zoom level:
// Galaxy view:  1.8  (subtle, ambient)
// Sector view:  2.2  (noticeable)
// System view:  2.5  (clear flash)
// Star view:    3.0  (vivid)
```

### Decay rates per zoom level

```javascript
// Slower decay at higher zoom = more dramatic, longer-lasting events
const DECAY = {
  galaxy: 0.0008,   // ~20s to fully fade
  sector: 0.0012,   // ~13s
  system: 0.0018,   // ~9s
  star:   0.0025,   // ~6s
};
```

### Cascade timing

```
t=0ms     hit entities flash (activityGlow → 1.0)
t=80ms    their documents brighten (activityGlow → 0.7)
t=180ms   domain brightens (activityGlow → 0.6)
t=300ms   route pulse begins traveling
t=500ms   connected domain/entity receives secondary pulse (0.4)
t=900ms   route pulse arrives, destination pulses
```

Stagger implemented with `setTimeout` chains, not physics. Simple and predictable.

### Persistence at scale

At high query frequency, entities that keep getting hit never fully decay before the next hit arrives. Their `activityGlow` accumulates toward a persistent elevated level:

```javascript
// On hit:
node.activityGlow = Math.min(1.0, node.activityGlow + 0.7);
// → frequently hit nodes stay persistently warm
// → rarely hit nodes are always dim
```

No additional mechanics needed. The heat map emerges naturally from repeated hits.

---

## Zoom transition system

### Thresholds

```javascript
const ZOOM_LEVELS = {
  galaxy: { max: 0.35 },
  sector: { min: 0.35, max: 0.75 },
  system: { min: 0.75, max: 1.50 },
  star:   { min: 1.50 },
};
```

### Cross-fade between levels

When zoom crosses a threshold, the outgoing level fades out over 40 frames while the incoming level fades in. Never an instant switch.

```javascript
let levelAlpha = { galaxy:1, sector:0, system:0, star:0 };

function updateLevelAlphas(zoom) {
  const target = getCurrentLevel(zoom);
  Object.keys(levelAlpha).forEach(level => {
    const isTarget = level === target;
    levelAlpha[level] = Math.min(1, Math.max(0,
      levelAlpha[level] + (isTarget ? 0.04 : -0.04)
    ));
  });
}

// In render loop — draw each level multiplied by its alpha
// Allows two levels to be simultaneously visible during transition
```

### Camera fly animation

Triggered by click at any level. Eases to target position and zoom over 800ms.

```javascript
function flyTo(targetX, targetY, targetZoom, duration = 800) {
  // Ease-in-out cubic
  const startX = camera.x, startY = camera.y, startZoom = camera.zoom;
  const start = performance.now();
  function animate(t) {
    const p = Math.min(1, (t - start) / duration);
    const ep = p < 0.5 ? 4*p*p*p : 1-Math.pow(-2*p+2,3)/2;
    camera.x    = startX    + (targetX    - startX)    * ep;
    camera.y    = startY    + (targetY    - startY)    * ep;
    camera.zoom = startZoom + (targetZoom - startZoom) * ep;
    if (p < 1) requestAnimationFrame(animate);
  }
  requestAnimationFrame(animate);
}
```

---

## LOD — what renders at each zoom

```
                  Galaxy  Sector  System  Star
Cluster cloud       ✓       ·       ·      ·
Domain nebula       ✓       ✓       ✓      ·  (bg hint)
Domain label        ·       ✓       ·      ·
Entity stars        ·       top20   ✓      ✓
Entity labels       ·       hover   top30% ✓
Doc stars           ·       ·       ·      ✓
Doc labels          ·       ·       ·      ✓
Trade routes        faint   ✓       ·      ·
Connection lines    ·       ·       ·      ✓
Activity pulse      ✓       ✓       ✓      ✓
```

---

## Left sidebar integration

The left sidebar panel (galaxy_interaction_spec.md) works at all zoom levels:

- **Galaxy:** click cluster → panel shows cluster summary
- **Sector:** click domain/entity → entity or domain panel
- **System:** click entity → entity panel
- **Star:** click doc → doc panel (or open reader); click entity → entity panel

The panel slides in from the left, the viz viewport shrinks from the left edge to accommodate. Dismisses on click-away or escape.

---

## Implementation phases

### Phase 1 — World space + galaxy view (start here)
- World space coordinate system with UMAP scaling
- Minimum domain separation enforcement at init
- Cluster computation from UMAP proximity
- Galaxy view rendering: cluster clouds + domain nebulae states
- Ambient activity: cluster brightness accumulation + domain pulse
- Cross-cluster route shimmer

### Phase 2 — Orbital entity physics
- Deterministic entity position from cubed domain weights
- Seeded orbital drift (slow ellipses)
- Entity size scaling (sqrt source_count)
- System view rendering with orbital entities

### Phase 3 — Sector view + trade routes
- Sector view rendering: domain nebulae at scale
- Trade route weight encoding (thickness, opacity, labels)
- Bridge entity positioning (interstitial space)
- Sector activity cascade (domain pulse + route pulse)

### Phase 4 — Star view + 2-hop graph
- Local graph assembly (hop-1 docs, hop-1 entities, hop-2)
- Document rendering (size by entity count, multi-domain indicator)
- Re-centering on click (constellation rebuild)
- Star view activity cascade
- Double-click → document reader

### Phase 5 — Zoom transitions + unified activity
- Cross-fade between zoom levels
- Camera fly animation
- Unified postMessage activity system
- Cascade timing across all levels
- Persistence/heat accumulation

---

## What does NOT change

- UMAP domain initialization — unchanged
- Existing pan/zoom controls — unchanged (just has more world)
- Document reader — unchanged (exit hatch from star view)
- Left sidebar panel components — unchanged
- postMessage bridge structure — unchanged
- The existing LOD system — recalibrated to new zoom thresholds, not replaced
