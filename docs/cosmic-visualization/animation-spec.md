# Galaxy Animation — Implementation Spec

Detailed Canvas2D rendering code for the cosmic visualization. Covers domain lifecycle states, activity system, pulses, trade routes, entity stars, and the render loop.

**Note:** This spec was written before UMAP-anchored domain positions were implemented. Seeded randomness (`seededRandom`) is NOT needed — domain positions come from UMAP embeddings, entity positions come from force simulation toward domain centroids. The deterministic layout comes from the data, not from seeded RNG.

**Note:** The rendering constants here use millisecond-based timing (`t * 0.0003`). The prototype at `noospheric/cosmic-viz/index.html` uses frame-tick-based timing (`tick * 0.0003`). Either works — just be consistent. The prototype runs at ~60fps so 1 frame ≈ 16.6ms.

---

## Domain States

Three visual states based on lifecycle:

### Unformed (no spec)
Dim rotating gas cloud, no core. Activity boost on search hit.
- 4 counter-rotating cloud layers
- Alpha: 0.022 base (very faint)
- No star core — just diffuse gas

### Simmering (spec being built)
Amber/orange override regardless of domain color — immediately recognizable as "active process."
- Normal cloud layers (slightly brighter)
- Amber infrared cocoon pulsing at center
- Flickering protostar core (irregular — two multiplied sine waves)
- Bipolar jets rotating slowly from core

### Formed (has spec)
Settled cloud with inner clearing, bright star core, diffraction spikes encoding maturity.
- Cloud layers with inner clearing (gradient starts at radius*0.25, not 0)
- Wide + inner stellar halo
- White star point at center
- Diffraction spikes at maturity ≥ 0.5 (length encodes subdomain coverage)
- Activity ring on search hit

Maturity calculation:
```
maturity = spec exists ? 0.5 + (simmeredSubdomains / totalSubdomains) * 0.5 : 0
if no subdomains and spec exists: maturity = 1.0
```

---

## Activity System

Every node (domain, entity) has `activityGlow: 0–1`.

**Decay per frame:**
- Galaxy view: 0.0008/ms (slow, ambient)
- Sector view: 0.0012/ms (faster, specific)

**On search hit:**
1. Flash hit entities immediately (+0.85)
2. Brighten their domains after 80ms (+0.7)
3. Fire route pulses after 250ms

Heat accumulates — frequently-hit nodes stay warm. A node hit at 2+/second stays near peak continuously. The heat map emerges from decay physics, no special mechanics.

---

## Activity Pulses

Glowing dots traveling between domains along trade routes.

- Ease-in-out travel (accelerate → peak → decelerate)
- Sine envelope brightness (peak at midpoint)
- Short trailing glow behind the dot
- Arrival ripple expands from destination in final 18% of travel
- On arrival: destination domain gets +0.5 activityGlow

Speed: 0.004–0.009 progress units per ms.

---

## Trade Routes (sector view)

Permanent dashed cyan lines. Weight encoded in thickness AND opacity.

- Alpha: 0.06 + normalized_weight * 0.08
- Thickness: 0.5 + normalized_weight * 1.5
- Brighter midpoint gradient
- Weight label shown on connections ≥ 20 shared entities

---

## Entity Stars

Small glowing points. Size = sqrt(source_count). Color = entity type.

| Type | Color |
|------|-------|
| Person | #7F77DD |
| Organization | #378ADD |
| Product | #1D9E75 |
| Technology | #BA7517 |
| Event | #D85A30 |
| Concept | #9c9a92 |
| Location | #5DCAA5 |

Features:
- Outer halo + white-core star point
- Activity ring on search hit
- Bridge indicator ring for multi-domain entities

---

## Render Loop Order

1. Clear + star field background
2. Trade routes (behind everything)
3. Domain nebulae
4. Entity stars (sector+ zoom only)
5. Activity pulses (on top)
6. Decay all activity values

---

## Key Numbers

```
Cloud layers:        4
Cloud alpha base:    0.022 (unformed), 0.045 (formed)
Cloud rotation:      0.0003 rad/ms
Core size:           0.055–0.090 × nebula radius
Spike length:        4–14 × core radius
Activity add:        +0.85 per hit
Activity decay:      0.0008/ms (galaxy), 0.0012/ms (sector)
Pulse dot size:      8–12 px
Entity radius:       1.5 + sqrt(source_count) * 0.9
Background stars:    150
Star twinkle speed:  0.0002–0.0006
```

---

## Full Reference Code

The complete Canvas2D implementation for each visual element (with exact gradient stops, alpha values, and animation curves) is in the source spec. Key functions:

- `drawUnformedNebula(ctx, x, y, radius, hexColor, activityGlow, t)`
- `drawSimmeringNebula(ctx, x, y, radius, hexColor, t)`
- `drawFormedNebula(ctx, x, y, radius, hexColor, maturity, activityGlow, t)`
- `drawPulse(ctx, pulse)` + `updatePulse(pulse, dt)`
- `drawTradeRoute(ctx, routeA, routeB, weight, maxWeight)`
- `drawEntityStar(ctx, x, y, entity, activityGlow, isHovered)`
- `drawDomainLabel(ctx, domain, x, y, radius)`
- `drawTooltip(ctx, x, y, title, lines, hexColor)`
- `triggerActivity(entityNames, domains, entities, routes, tradeRoutes)`

Working prototype with all of these implemented: `noospheric/cosmic-viz/index.html`
