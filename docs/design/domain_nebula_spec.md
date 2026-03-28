# Domain Nebula Visual Encoding — Implementation Spec

## Scope

This spec covers changes to the domain nebula rendering inside `cosmic-viz.html`. No other systems are affected. The entity stars, trade routes, physics, LOD system, and interaction model are all unchanged.

The goal is to make domain nebulae visually encode their development state — how much of the domain and its subtree has been understood by the system. Currently all domains look the same regardless of whether they have a spec or 10 unsimmered subdomains beneath them. After this change, a user should be able to look at the galaxy and immediately read which domains are mapped and which are dark matter.

---

## Concept: maturity score

Every domain gets a `maturity` value between 0.0 and 1.0, computed from:

1. **Own spec** — does this domain have a simmered extraction spec?
2. **Subdomain coverage** — of the subdomains beneath this domain, how many have specs?
3. **Currently simmering** — is a simmer job actively running for this domain?

This replaces any notion of "spec version number." There is no v1/v2/v3 — maturity is a continuous value derived from the subtree structure.

### Maturity calculation

```javascript
function computeMaturity(domain, allDomains) {
  const hasSpec = domain.spec_version != null && domain.spec_version > 0;
  
  // Find direct and indirect subdomains
  const subdomains = allDomains.filter(d =>
    d.path.startsWith(domain.path + '/') &&
    d.path !== domain.path
  );
  
  if (subdomains.length === 0) {
    // Leaf domain — maturity is binary: has spec or not
    return hasSpec ? 1.0 : 0.0;
  }
  
  const subdomainsWithSpec = subdomains.filter(d =>
    d.spec_version != null && d.spec_version > 0
  );
  const subdomainCoverage = subdomainsWithSpec.length / subdomains.length;
  
  if (!hasSpec) {
    // No own spec — maturity capped at 0.4 even if children are simmered
    // Children being understood doesn't mean the parent is
    return subdomainCoverage * 0.4;
  }
  
  // Has own spec — base 0.5 + up to 0.5 from subdomain coverage
  return 0.5 + subdomainCoverage * 0.5;
}
```

Examples at a real corpus:
```
business/strategy                    has spec, 2/3 subdomains simmered  → maturity 0.83
business/strategy/marketing          has spec, 1/1 subdomain simmered   → maturity 1.0
business/strategy/marketing/social   has spec, no subdomains (leaf)     → maturity 1.0
business/strategy/ecomm              no spec, no subdomains             → maturity 0.0
business/strategy/partnerships       no spec, no subdomains             → maturity 0.0
```

### Simmering state

Simmering is a separate boolean that overrides the normal rendering entirely. Check for active jobs:

```javascript
function isCurrentlySimmering(domain, activeJobs) {
  return activeJobs.some(j =>
    j.type === 'simmer_domain' &&
    j.target === domain.path &&
    j.status === 'running'
  );
}
```

A domain can be simmering at any maturity level — it might be re-simmering a high-maturity domain after new docs were added.

---

## Three rendering states

Every domain falls into exactly one of these states, checked in this order:

1. **Simmering** — `isCurrentlySimmering` is true → amber protostar rendering
2. **Formed** — `maturity > 0` → star present, brightness/spikes scale with maturity
3. **Unformed** — `maturity === 0` → wispy cloud only, no star

---

## State 1: Unformed (no spec, no simmered children)

```
Visual:    diffuse gas cloud, no central concentration
Color:     domain's existing region_color (unchanged)
Alpha:     very low — 0.02–0.04 across layers
Animation: slow rotation of cloud layers (existing behavior, unchanged)
Core:      none — no star, no glow at center
```

This is the current rendering behavior for most domains, just made explicit. The only tuning needed: make sure the cloud alpha stays genuinely low so unformed domains read as undiscovered rather than just dim.

**Canvas2D implementation** (matches existing pattern, parametrized):

```javascript
function drawUnformed(ctx, cx, cy, radius, color, t) {
  const layers = 4;
  for (let i = 0; i < layers; i++) {
    const angle = t * 0.0003 * (i % 2 === 0 ? 1 : -1) + (i * Math.PI * 2 / layers);
    const ox = Math.cos(angle) * radius * 0.12;
    const oy = Math.sin(angle) * radius * 0.08;
    const r = radius * (1.8 - i * 0.12);
    const alpha = 0.022 - i * 0.003;

    const grad = ctx.createRadialGradient(cx+ox, cy+oy, 0, cx+ox, cy+oy, r);
    grad.addColorStop(0, colorWithAlpha(color, alpha * 2));
    grad.addColorStop(0.4, colorWithAlpha(color, alpha));
    grad.addColorStop(1, colorWithAlpha(color, 0));
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(cx+ox, cy+oy, r, 0, Math.PI * 2);
    ctx.fill();
  }
  // No core — stop here
}
```

---

## State 2: Simmering (active simmer job running)

```
Visual:    gas cloud + flickering amber/orange core + faint bipolar jets
Color:     domain color for cloud, amber/orange for core (hardcoded, not domain color)
Animation: irregular flicker on core, slow jet rotation, cloud rotation
Core:      unstable, warm, partially hidden — like infrared protostar inside dust
```

The amber color is intentional and fixed — it comes from the astrophysics of protostars (dust heated to infrared by the forming star). It is always amber regardless of domain color. This makes simmering domains immediately recognizable at a glance.

**Canvas2D implementation:**

```javascript
function drawSimmering(ctx, cx, cy, radius, color, t) {
  // Cloud layers — slightly brighter than unformed
  const layers = 4;
  for (let i = 0; i < layers; i++) {
    const angle = t * 0.0006 * (i % 2 === 0 ? 1 : -1) + (i * Math.PI * 2 / layers);
    const ox = Math.cos(angle) * radius * 0.10;
    const oy = Math.sin(angle) * radius * 0.08;
    const r = radius * (1.6 - i * 0.10);
    const alpha = 0.032 - i * 0.003;

    const grad = ctx.createRadialGradient(cx+ox, cy+oy, 0, cx+ox, cy+oy, r);
    grad.addColorStop(0, colorWithAlpha(color, alpha * 2));
    grad.addColorStop(0.5, colorWithAlpha(color, alpha));
    grad.addColorStop(1, colorWithAlpha(color, 0));
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(cx+ox, cy+oy, r, 0, Math.PI * 2);
    ctx.fill();
  }

  // Infrared cocoon — amber glow, pulses slowly
  const pulse = 0.7 + 0.3 * Math.sin(t * 0.003);
  const cocoon = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius * 0.55);
  cocoon.addColorStop(0, `rgba(255,160,60,${0.14 * pulse})`);
  cocoon.addColorStop(0.5, `rgba(220,100,30,${0.07 * pulse})`);
  cocoon.addColorStop(1, `rgba(180,60,10,0)`);
  ctx.fillStyle = cocoon;
  ctx.beginPath();
  ctx.arc(cx, cy, radius * 0.55, 0, Math.PI * 2);
  ctx.fill();

  // Flickering protostar core — irregular, not a clean sine
  const flicker = 0.5 + 0.5 * Math.sin(t * 0.007 + Math.sin(t * 0.013));
  const coreR = radius * 0.09 * (0.8 + 0.2 * flicker);

  const halo = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreR * 4);
  halo.addColorStop(0, `rgba(255,180,80,${0.20 * flicker})`);
  halo.addColorStop(0.3, `rgba(255,120,40,${0.10 * flicker})`);
  halo.addColorStop(1, `rgba(200,80,20,0)`);
  ctx.fillStyle = halo;
  ctx.beginPath();
  ctx.arc(cx, cy, coreR * 4, 0, Math.PI * 2);
  ctx.fill();

  const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreR);
  core.addColorStop(0, `rgba(255,240,200,${0.65 * flicker})`);
  core.addColorStop(0.5, `rgba(255,180,80,${0.40 * flicker})`);
  core.addColorStop(1, `rgba(255,120,40,0)`);
  ctx.fillStyle = core;
  ctx.beginPath();
  ctx.arc(cx, cy, coreR, 0, Math.PI * 2);
  ctx.fill();

  // Bipolar jets — thin, faint, slowly rotating
  // Physically accurate: protostars emit jets perpendicular to accretion disk
  const jetAngle = t * 0.0008;
  const jetLen = radius * 0.40;
  const jetAlpha = 0.07 * flicker;
  for (let d = 0; d < 2; d++) {
    const a = jetAngle + d * Math.PI;
    const jetGrad = ctx.createLinearGradient(
      cx, cy,
      cx + Math.cos(a) * jetLen,
      cy + Math.sin(a) * jetLen
    );
    jetGrad.addColorStop(0, `rgba(255,200,100,${jetAlpha})`);
    jetGrad.addColorStop(1, `rgba(255,150,50,0)`);
    ctx.strokeStyle = jetGrad;
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.cos(a) * jetLen, cy + Math.sin(a) * jetLen);
    ctx.stroke();
  }
}
```

---

## State 3: Formed (maturity > 0)

```
Visual:    settled cloud with inner clearing + stable star at center
Color:     domain color for cloud, domain color for star halo, white for star point
Animation: very slow cloud rotation, gentle star breathing (barely perceptible)
Core:      clean, stable — brightness and spike length scale with maturity
```

The inner clearing in the cloud (the evacuated zone near the star) is physically motivated — radiation pressure from a formed star pushes surrounding gas outward, thinning the nebula near the core.

**Maturity → visual parameters:**

```javascript
// maturity is 0.0–1.0
const starBrightness  = 0.4 + maturity * 0.6;      // 0.4 at maturity 0.01, 1.0 at maturity 1.0
const coreRadius      = radius * (0.055 + maturity * 0.035);  // grows slightly with maturity
const hasSpikeS       = maturity >= 0.5;            // spikes appear at 50% maturity
const spikeLength     = coreRadius * (4 + maturity * 10);     // 4× at 0.5, 14× at 1.0
const cloudAlpha      = 0.045 + maturity * 0.025;   // slightly brighter cloud in mature domains
```

**Canvas2D implementation:**

```javascript
function drawFormed(ctx, cx, cy, radius, color, maturity, t) {
  const bright = 0.4 + maturity * 0.6;
  const coreR = radius * (0.055 + maturity * 0.035);
  const breathe = 0.94 + 0.06 * Math.sin(t * 0.001); // very slow, stable

  // Settled cloud with inner clearing
  const layers = 4;
  for (let i = 0; i < layers; i++) {
    const angle = t * 0.0002 * (i % 2 === 0 ? 1 : -1) + (i * Math.PI * 2 / layers);
    const ox = Math.cos(angle) * radius * 0.07;
    const oy = Math.sin(angle) * radius * 0.06;
    const r = radius * (1.5 - i * 0.08);
    const baseAlpha = 0.045 + maturity * 0.025 - i * 0.005;

    const grad = ctx.createRadialGradient(cx+ox, cy+oy, radius * 0.25, cx+ox, cy+oy, r);
    grad.addColorStop(0, colorWithAlpha(color, 0));         // inner clearing
    grad.addColorStop(0.15, colorWithAlpha(color, baseAlpha * 1.5));
    grad.addColorStop(0.5, colorWithAlpha(color, baseAlpha));
    grad.addColorStop(1, colorWithAlpha(color, 0));
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(cx+ox, cy+oy, r, 0, Math.PI * 2);
    ctx.fill();
  }

  // Wide stellar halo
  const wideHalo = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius * 0.55);
  wideHalo.addColorStop(0, colorWithAlpha(color, 0.09 * bright));
  wideHalo.addColorStop(0.4, colorWithAlpha(color, 0.04 * bright));
  wideHalo.addColorStop(1, colorWithAlpha(color, 0));
  ctx.fillStyle = wideHalo;
  ctx.beginPath();
  ctx.arc(cx, cy, radius * 0.55, 0, Math.PI * 2);
  ctx.fill();

  // Inner halo
  const innerHalo = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreR * 5);
  innerHalo.addColorStop(0, colorWithAlpha(color, 0.28 * bright * breathe));
  innerHalo.addColorStop(0.4, colorWithAlpha(color, 0.13 * bright));
  innerHalo.addColorStop(1, colorWithAlpha(color, 0));
  ctx.fillStyle = innerHalo;
  ctx.beginPath();
  ctx.arc(cx, cy, coreR * 5, 0, Math.PI * 2);
  ctx.fill();

  // Star point — white center, domain color halo
  const starGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreR);
  starGrad.addColorStop(0, `rgba(255,255,255,${0.92 * bright * breathe})`);
  starGrad.addColorStop(0.3, colorWithAlpha(color, 0.7 * bright));
  starGrad.addColorStop(1, colorWithAlpha(color, 0));
  ctx.fillStyle = starGrad;
  ctx.beginPath();
  ctx.arc(cx, cy, coreR, 0, Math.PI * 2);
  ctx.fill();

  // Diffraction spikes — appear at maturity >= 0.5, grow with maturity
  // These encode subdomain coverage — longer spikes = more of the subtree is understood
  if (maturity >= 0.5) {
    const spikeLen = coreR * (4 + maturity * 10);
    const spikeAlpha = bright * 0.28 * breathe;
    for (let s = 0; s < 4; s++) {
      const a = s * Math.PI / 2;
      const x2 = cx + Math.cos(a) * spikeLen;
      const y2 = cy + Math.sin(a) * spikeLen;
      const spikeGrad = ctx.createLinearGradient(cx, cy, x2, y2);
      spikeGrad.addColorStop(0, `rgba(255,255,255,${spikeAlpha})`);
      spikeGrad.addColorStop(1, colorWithAlpha(color, 0));
      ctx.strokeStyle = spikeGrad;
      ctx.lineWidth = 0.8;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(x2, y2);
      ctx.stroke();
    }
  }
}
```

---

## Radius scaling

Cloud radius already scales with doc count. Keep the existing formula but make it slightly more aggressive so size differences read clearly at the zoom levels users commonly use:

```javascript
// Current (keep if works, or adjust multiplier):
const radius = 30 + Math.sqrt(domain.document_count) * 8;

// If differences aren't reading clearly at typical zoom, increase multiplier to 10–12
// The key is that a 6-doc domain and a 45-doc domain should look obviously different
```

---

## Data requirements

Everything needed is already in `GET /graph` or derivable from it. No new endpoints.

The viz currently receives:
- `domain_positions` — ✓ has path
- `domain_video_counts` — ✓ doc count (used for radius, unchanged)
- `region_colors` — ✓ domain color (unchanged)

**New fields needed in the graph response** (or fetch separately):

```javascript
// Add to GET /graph response, or derive client-side if domains are already fetched:
domain_specs: {
  "business/strategy": { spec_version: 1 },
  "business/strategy/marketing": { spec_version: 1 },
  "business/strategy/marketing/social": { spec_version: 1 },
  "business/strategy/ecomm": null,
}

// Active simmer jobs — already available via GET /jobs polling
// The viz already polls /jobs every 5s — use that to identify simmering domains
```

If adding `domain_specs` to `/graph` is too large a change, an alternative is `GET /domains` which already returns `spec_version` per domain — fetch once on viz load and cache.

---

## Helper function

```javascript
// Used throughout — converts an HSL or hex color + alpha to rgba string
// The viz already has region_colors as hex strings
function colorWithAlpha(hexColor, alpha) {
  const r = parseInt(hexColor.slice(1,3), 16);
  const g = parseInt(hexColor.slice(3,5), 16);
  const b = parseInt(hexColor.slice(5,7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}
```

---

## Integration into existing render loop

The existing domain rendering is in the main `drawDomains()` or equivalent function. Replace the current single rendering path with a state check:

```javascript
domains.forEach(domain => {
  const simmering = isCurrentlySimmering(domain, activeJobs);
  const maturity = computeMaturity(domain, allDomains);

  if (simmering) {
    drawSimmering(ctx, domain.x, domain.y, domain.radius, domain.color, t);
  } else if (maturity > 0) {
    drawFormed(ctx, domain.x, domain.y, domain.radius, domain.color, maturity, t);
  } else {
    drawUnformed(ctx, domain.x, domain.y, domain.radius, domain.color, t);
  }
});
```

The `domain.radius` is computed once from doc count (existing behavior). The `domain.color` comes from `region_colors` (existing). Only the rendering function changes.

---

## What does NOT change

- Entity star rendering — unchanged
- Trade route rendering — unchanged
- Physics / orbit simulation — unchanged
- LOD system — unchanged
- Existing hover/pin interaction — unchanged
- Domain label positions and typography — unchanged
- Zoom behavior — unchanged
- The tooltip simplification is covered in the Galaxy Interaction Layer spec (separate)

---

## Visual design intent summary

For the implementer — the goal is a legible narrative visible at a glance:

> A user panning the galaxy should be able to read, without tooltips or labels, which domains are raw/undiscovered (wispy, no core), which are actively being processed (amber flicker), and which are well understood (clean star, spikes proportional to how deep the understanding goes). The visual should feel like looking at a real star-forming region — some areas are dark clouds, some have protostars heating up inside, some have ignited into proper stars with the surrounding gas pushed outward.

The amber simmering color is the one deliberate departure from the domain's region color — it should stand out as "something is happening here right now." Everything else uses the domain's own color.
