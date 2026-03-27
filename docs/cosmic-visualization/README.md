# Cosmic Knowledge Graph Visualization

An interactive galaxy map visualizing a living knowledge graph. Domains are nebulae, entities are stars, documents are comets. The visual form encodes lifecycle state, connectivity, and semantic position.

## Metaphor

| Graph Concept | Visual Object |
|---|---|
| Domain (accumulating) | Nebula — swirling gas cloud with progress arc |
| Domain (simmering) | Protostar — flickering, ejecting sparks |
| Domain (active) | Star — clean rays, glowing core |
| Entity | Star floating inside domain nebula gravity well |
| Multi-domain entity | Star with blended colors, positioned at weighted midpoint |
| Document ingest | Comet flying from edge to target domain |
| Cross-domain link | Dashed cyan trade route with flowing particles |
| Subdomain | Smaller nebula near parent, offset in semantic direction |

## Two-Layer Architecture

```
┌───────────────────────────────────────────────────┐
│  LAYER 1: SEMANTIC SKELETON (domains)             │
│  Positions from UMAP projection of embeddings.    │
│  Stable. New arrivals placed by transform().      │
│  The bones of the galaxy don't move.              │
├───────────────────────────────────────────────────┤
│  LAYER 2: ORGANIC INTERIOR (entities)             │
│  Positions from attraction forces only.           │
│  Stars float toward their domain centroid(s).     │
│  Age-weighted stability: old stars barely move.   │
└───────────────────────────────────────────────────┘
```

Different physics for each layer. No global repulsion between entities. Entities attract toward domain centroids and repel only within their local domain.

## Force Stack

**Domain nodes:**
1. Semantic anchor toward UMAP position (strength 0.82–0.95)
2. Collision prevention between domains
3. Very weak center gravity (0.0002)

**Entity nodes:**
1. Attraction toward domain centroid(s), weighted by association strength
2. Slow tangential orbital drift (0.015)
3. Local collision among nearby entities (radius 50)
4. Age-weighted velocity damping (stability 0–0.9)
5. Velocity cap (1.5 px/frame)

**Not used:** global charge repulsion, link forces between unrelated entities, link forces between domains.

## LOD (Level of Detail)

| Zoom Level | Visible |
|---|---|
| < 0.25 | Nebulae only |
| 0.25–0.4 | + trade routes |
| 0.4+ | + entity stars |
| 0.7+ | + entity labels |

## Visual Elements

### Nebula (domain)
- 4 rotating gas layers with radial gradients (rotation: 0.0003/frame)
- Dim core glow
- Color from top-level region palette
- Subdomains: smaller radius, dimmer, label shows leaf name only

### Star (entity)
- Radial gradient core with aura
- Shadow glow on hover
- Color: blended from parent domain colors, weighted by association strength
- Radius: 2 + min(sqrt(videoCount) * 0.8, 8)

### Trade routes
- Dashed cyan lines between domains sharing entities
- Slow-moving particles along the route (speed: 0.001)
- Opacity: 0.08 default, 0.45 on hover highlight

### Comets
- Point head with fading trail (18 segments)
- Fly from edge of canvas toward target domain
- On impact: birth ring animation + domain doc count increment

### Birth rings
- 3 concentric expanding circles
- Fade over 1.4 seconds
- Color matches the spawning event

### Sparks
- Ejected particles from simmering protostars
- Decelerate over 0.03 lifetime increments
- Rate scales with simmer progress

## Rendering

Canvas2D at 60fps. Background (starfield + nebula clouds) drawn in screen space. All graph content drawn in world space with camera transform (translate + scale).

Camera: scroll to zoom (0.12x–5x), drag to pan. Pointer cursor on nodes.

## Data Format

`cosmic_data_v4.json`:
```json
{
  "domain_positions": {"techniques/nmm": {"x": 0.7, "y": 0.07}},
  "domain_video_counts": {"techniques/nmm": 4},
  "region_colors": {"techniques": "#f97316"},
  "subdomains": ["techniques/blending/wet-on-wet"],
  "videos": [{"id": "...", "title": "...", "domains": [...], "primary": "...", "isV3": true}],
  "entities": [{"name": "...", "type": "...", "videoCount": 13, "domainWeights": {"dom": 0.5}}],
  "v3_entities": [{"name": "...", "type": "..."}],
  "trade_routes": [{"source": "dom:a", "target": "dom:b", "weight": 5}]
}
```

## Demo Controls

- **INGEST DOC** — launches a comet toward a random domain
- **DOC BURST ×8** — 8 comets with staggered timing
- **SIMMER DOMAIN** — spawns new subdomain near V3 tutorials' parent domains, 6s of sparks, then spawns V3 entities. Overlapping V2 entities get strengthened (pulsed green, grown), new entities spawn fresh.

## Lessons Learned

1. **Entities as stars with tutorials as planets didn't work.** Everything clumped because tutorials connect to many entity hubs. Switched to domains as nebulae (spatial regions) with entities floating inside.
2. **UMAP for domain layout works well.** Semantically similar domains land near each other without manual placement. Stable across new arrivals.
3. **No global repulsion.** The key insight. Repulsion between all entities causes reshuffling and hairball formation. Only local collision within domains.
4. **Domain classification drives everything.** Tried community detection (Leiden) first — gives clusters but doesn't tell you what they mean. LLM classification does both: discover + name + assign.
5. **Multi-domain entity positioning.** Entities in 2+ domains settle at the weighted midpoint. Visually correct and semantically meaningful.
6. **Particles should be slow.** 0.001 speed, not 0.004+. Otherwise it's a strobe at galaxy scale.

## Location

- **Viz:** `noospheric/cosmic-viz/index.html`
- **Data:** `noospheric/cosmic-viz/cosmic_data_v4.json`
- **Spec:** User provided a full rendering spec with pseudocode for all visual elements
- **Graph panel (React):** `noospheric/frontend/src/components/learn/graph-panel.tsx`
- **Standalone explorer:** `DS-scratch/.../viz_graph.html` + `graph-renderer.js`
