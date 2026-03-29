# Search Neighborhood Glow — Implementation Spec

## What this is

When a search completes, the nodes that contributed to the result light up in the galaxy viz. This is the primitive that future agent activity visualization builds on — nail the single-query version first, then scale and complexity comes later.

This spec covers:
1. The postMessage contract between parent page and viz iframe
2. Three visual effects inside the viz (star flash, domain brighten, route pulse)
3. How they sequence and feel

Nothing else changes. No new data fetching, no new physics, no structural changes to the viz.

---

## Design intent

The effect should feel like **bioluminescence** — brief, organic, meaningful. Not a UI notification. Not a loading spinner. Something that happens *in the world of the viz*, not on top of it.

Three principles:
- **Fast.** The whole sequence completes in under 2 seconds. It marks the moment a search happened, then the galaxy returns to its normal state.
- **Spatial.** The light travels outward from the hit nodes through the graph topology. Stars flash first, then their domains brighten, then routes pulse outward. The sequence follows the structure.
- **Sine-curve brightness.** All glow values use `sin(progress * π)` — ease in, peak, ease out. Linear fades feel mechanical. Sine curves feel physical, like something briefly energized then settling.

---

## postMessage contract

The parent page fires this after any search completes:

```javascript
galaxyIframe.contentWindow.postMessage({
  type: 'search_result',
  entities: ['harper reed', 'dylan richard', 'betaworks'],  // canonical names
  routes: [                                                   // optional
    ['business/strategy', 'business/fundraising'],
    ['business/fundraising', 'business/vc_firms']
  ]
}, '*');
```

**`entities`** — canonical names of entities that contributed to the result. These are the nodes that get lit. Required.

**`routes`** — domain path pairs representing graph edges traversed during retrieval. Optional for v1 — if not provided, the viz derives candidate routes from the hit entities' domain weights. Add explicit route data later when the retrieval walk is wired up.

The viz listens:

```javascript
window.addEventListener('message', e => {
  if (e.data?.type === 'search_result') {
    triggerSearchGlow(e.data.entities, e.data.routes || null);
  }
});
```

---

## Animation state

Add these fields to each node object. They are `null` when inactive — check for null before reading in the draw loop.

```javascript
// On entity nodes:
node.glowStart = null;      // timestamp when glow began
node.glowDuration = 1400;   // ms, star flash duration

// On domain nodes:
domain.brightenStart = null;
domain.brightenDuration = 1800;  // slightly longer than star

// On trade route objects:
route.pulseStart = null;
route.pulseDuration = 900;   // ms for pulse to travel full length
route.pulseDelay = 0;        // stagger for sequential routes
```

---

## triggerSearchGlow

```javascript
function triggerSearchGlow(entityNames, explicitRoutes) {
  const now = performance.now();

  // 1. Find hit entity nodes
  const hitNodes = nodes.filter(n =>
    entityNames.includes(n.name) || entityNames.includes(n.canonical_name)
  );
  if (hitNodes.length === 0) return;

  // 2. Flash each hit star — staggered slightly so they don't all pop at once
  hitNodes.forEach((node, i) => {
    node.glowStart = now + i * 40;  // 40ms stagger between stars
  });

  // 3. Find affected domains from hit nodes' domainWeights
  const hitDomainPaths = new Set(
    hitNodes.flatMap(n => Object.keys(n.domainWeights || {}))
  );

  // 4. Brighten affected domains — delayed after star flash peaks
  const domainDelay = 200;
  hitDomainPaths.forEach(path => {
    const domain = domains.find(d => d.path === path);
    if (domain) domain.brightenStart = now + domainDelay;
  });

  // 5. Pulse routes
  // Use explicit routes if provided, otherwise use routes connecting hit domains
  const routesToPulse = explicitRoutes
    ? explicitRoutes
    : tradeRoutes.filter(r =>
        hitDomainPaths.has(r.source) && hitDomainPaths.has(r.target)
      ).map(r => [r.source, r.target]);

  // Stagger route pulses sequentially
  routesToPulse.forEach(([src, tgt], i) => {
    const route = tradeRoutes.find(r =>
      (r.source === src && r.target === tgt) ||
      (r.source === tgt && r.target === src)
    );
    if (route) {
      route.pulseStart = now + domainDelay + i * 150;
    }
  });
}
```

---

## Draw loop integration

### Entity star glow

In the existing star draw function, after drawing the normal star, add:

```javascript
function getGlowFactor(startTime, duration) {
  if (startTime === null) return 0;
  const now = performance.now();
  const elapsed = now - startTime;
  if (elapsed < 0 || elapsed > duration) return 0;
  // Sine curve: 0 → 1 → 0 over duration
  return Math.sin((elapsed / duration) * Math.PI);
}

// When drawing each entity star:
const glow = getGlowFactor(node.glowStart, node.glowDuration);

if (glow > 0) {
  // Outer bloom — wide, low alpha
  const bloom = ctx.createRadialGradient(x, y, 0, x, y, starRadius * 6);
  bloom.addColorStop(0, colorWithAlpha(node.color, 0.35 * glow));
  bloom.addColorStop(0.4, colorWithAlpha(node.color, 0.15 * glow));
  bloom.addColorStop(1, colorWithAlpha(node.color, 0));
  ctx.fillStyle = bloom;
  ctx.beginPath();
  ctx.arc(x, y, starRadius * 6, 0, Math.PI * 2);
  ctx.fill();

  // Inner ring — crisp bright edge at peak
  const ring = ctx.createRadialGradient(x, y, starRadius * 0.8, x, y, starRadius * 2.5);
  ring.addColorStop(0, colorWithAlpha('#ffffff', 0.7 * glow));
  ring.addColorStop(0.5, colorWithAlpha(node.color, 0.4 * glow));
  ring.addColorStop(1, colorWithAlpha(node.color, 0));
  ctx.fillStyle = ring;
  ctx.beginPath();
  ctx.arc(x, y, starRadius * 2.5, 0, Math.PI * 2);
  ctx.fill();
}

// Clean up — reset after animation completes
if (node.glowStart !== null) {
  const elapsed = performance.now() - node.glowStart;
  if (elapsed > node.glowDuration) node.glowStart = null;
}
```

**Visual result:** a brief white-core bloom that expands and fades. The inner ring gives a crisp "ignition" feeling at the peak. The outer bloom is wide and soft — more nebular than sharp.

---

### Domain brighten

In the existing domain nebula draw function, multiply the base cloud alpha by a brighten factor:

```javascript
const brighten = getGlowFactor(domain.brightenStart, domain.brightenDuration);

// Apply to the alpha values in drawFormed / drawUnformed / drawSimmering:
const baseAlpha = 0.045 + maturity * 0.025;
const effectiveAlpha = baseAlpha * (1 + brighten * 1.2);
// i.e. at peak, the cloud is 2.2× its normal brightness

// Also briefly boost the star core if formed:
const effectiveBrightness = bright * (1 + brighten * 0.5);

// Clean up:
if (domain.brightenStart !== null) {
  const elapsed = performance.now() - domain.brightenStart;
  if (elapsed > domain.brightenDuration) domain.brightenStart = null;
}
```

**Visual result:** the nebula briefly swells in brightness, then settles. On formed domains the star core also brightens. On unformed domains the dim cloud briefly becomes visible. The domain effect is softer and slower than the star flash — it's the environment responding, not a point event.

---

### Route pulse

A point of light travels along the trade route line from source domain to target domain.

```javascript
// When drawing each trade route:
const pulseFactor = getGlowFactor(route.pulseStart, route.pulseDuration);

if (pulseFactor > 0) {
  const elapsed = Math.max(0, performance.now() - route.pulseStart);
  // Progress 0→1 along the route, eased
  const rawProgress = Math.min(1, elapsed / route.pulseDuration);
  const progress = rawProgress < 0.5
    ? 2 * rawProgress * rawProgress
    : -1 + (4 - 2 * rawProgress) * rawProgress; // ease in-out

  // Interpolate position along route line
  const px = route.sourceX + (route.targetX - route.sourceX) * progress;
  const py = route.sourceY + (route.targetY - route.sourceY) * progress;

  // Traveling glow dot
  const dotGrad = ctx.createRadialGradient(px, py, 0, px, py, 8);
  dotGrad.addColorStop(0, `rgba(0,255,220,${0.9 * pulseFactor})`);
  dotGrad.addColorStop(0.3, `rgba(0,220,200,${0.5 * pulseFactor})`);
  dotGrad.addColorStop(1, `rgba(0,180,160,0)`);
  ctx.fillStyle = dotGrad;
  ctx.beginPath();
  ctx.arc(px, py, 8, 0, Math.PI * 2);
  ctx.fill();

  // Brief trail behind the dot
  const trailLen = 0.08; // 8% of route length
  const trailStart = Math.max(0, progress - trailLen);
  const tx = route.sourceX + (route.targetX - route.sourceX) * trailStart;
  const ty = route.sourceY + (route.targetY - route.sourceY) * trailStart;
  const trailGrad = ctx.createLinearGradient(tx, ty, px, py);
  trailGrad.addColorStop(0, `rgba(0,255,220,0)`);
  trailGrad.addColorStop(1, `rgba(0,255,220,${0.3 * pulseFactor})`);
  ctx.strokeStyle = trailGrad;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(tx, ty);
  ctx.lineTo(px, py);
  ctx.stroke();

  // Clean up:
  if (route.pulseStart !== null && rawProgress >= 1) {
    route.pulseStart = null;
  }
}
```

**Visual result:** a cyan dot (matching the existing trade route color) travels along the route with a short fading trail. The ease-in-out makes it accelerate then decelerate — like a signal propagating through a medium rather than a mechanical animation. The trail gives it a sense of motion even at a single frame.

---

## Timing summary

```
t=0ms       Star flashes begin (staggered 40ms apart)
t=40-200ms  Stars at peak brightness
t=200ms     Domain brightening begins
t=200-350ms Route pulses begin (staggered 150ms apart)
t=700ms     Stars fully faded
t=1100ms    Route pulses complete
t=2000ms    Domain brightening fully faded
```

The cascade reads: *something happened here → the neighborhood responded → the connections carried it outward*. Each layer settling before the next fades creates a sense of propagation rather than a simultaneous flash.

---

## Handling multiple searches

If a second search fires before the first animation completes, restart the animation on overlapping nodes:

```javascript
// In triggerSearchGlow, always overwrite existing glow state:
node.glowStart = now + i * 40;  // resets even if currently glowing
```

At low query frequency this creates clean sequential animations. At high frequency (future agent scale) nodes that are frequently hit will appear persistently bright because they keep getting reset before they fully fade — which is exactly the behavior wanted for the "organizational attention heat map" vision. The primitive scales naturally.

---

## What this is NOT

- Not a loading indicator — the animation fires after the result is ready
- Not a selection state — it fades completely, leaving no persistent mark
- Not tied to the panel — the glow happens in the viz regardless of whether the panel is open

The panel (galaxy interaction spec) handles showing *what* was found. The glow handles showing *where* in the graph it came from. They are independent.

---

## Future extensions (not in this spec)

- **Persistence with decay:** instead of resetting glow to 0 on completion, accumulate a small residual brightness per hit that decays over minutes. Frequently queried nodes glow slightly warmer than cold ones. One multiplier field per node.
- **Multiple simultaneous queries:** each query gets its own color tint so you can distinguish different agents' activity. Requires passing a `query_id` or `agent_id` in the postMessage.
- **Intensity scales with result confidence:** nodes that scored highest in retrieval get a brighter flash. Pass a score alongside each entity name.
