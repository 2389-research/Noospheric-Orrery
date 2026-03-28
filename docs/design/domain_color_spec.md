# Domain Color System — Implementation Spec

## Problem

The current color system hashes the full domain path to an HSL hue. Because sibling domains share a common path prefix, they cluster in hue space and look visually similar. All `business/*` domains end up in the same color neighborhood regardless of how many there are or how distinct they are conceptually.

This gets worse at scale — a corpus with 30 subdomains under `business` will produce 30 nearly identical pinkish-purple nebulae that are impossible to tell apart.

## Solution: hierarchy-aware golden ratio distribution

Top-level domains each own a dedicated slice of the hue wheel. Within each slice, subdomains are spaced using the golden ratio — a technique that maximizes perceptual distance between sequentially assigned values and is self-similar at any scale.

**What this preserves:**
- Siblings are visually distinct from each other
- Domains under the same top-level parent share a hue family — you can see relatedness
- Fully deterministic — same domain tree always produces same colors
- Scales automatically — new domains take the next slot, no recalculation of existing assignments
- No manual curation required

**What this changes:**
- Existing domain colors will change. This is a one-time migration cost and is worth it.

---

## Hue assignment algorithm

```javascript
const GOLDEN_RATIO = 0.618033988749895;

function assignDomainColors(allDomains) {
  // Step 1: find all top-level domains, sort for determinism
  const topLevelNames = [...new Set(
    allDomains.map(d => d.path.split('/')[0])
  )].sort();

  // Step 2: divide the hue wheel evenly among top-level domains
  // Each gets an equal slice, spaced to maximise distance between them
  const topLevelHues = {};
  topLevelNames.forEach((name, i) => {
    topLevelHues[name] = (i / topLevelNames.length) * 360;
  });

  const sliceSize = 360 / topLevelNames.length;

  // Step 3: within each top-level slice, assign subdomains using golden ratio
  // Sort siblings alphabetically for determinism
  const colorMap = {};

  topLevelNames.forEach(topName => {
    const rangeStart = topLevelHues[topName];

    // All domains under this top-level, sorted by path for determinism
    const family = allDomains
      .filter(d => d.path.split('/')[0] === topName)
      .sort((a, b) => a.path.localeCompare(b.path));

    family.forEach((domain, i) => {
      // Golden ratio offset within the slice
      const offset = ((i * GOLDEN_RATIO) % 1) * sliceSize;
      const hue = (rangeStart + offset) % 360;
      colorMap[domain.path] = hslToHex(hue, SATURATION, LIGHTNESS);
    });
  });

  return colorMap;
}
```

---

## Fixed saturation and lightness

All domain nebulae use the same saturation and lightness — only hue varies. This keeps the visual language consistent (all nebulae look like nebulae) while maximizing color distinctiveness.

```javascript
const SATURATION = 65;   // % — vivid enough to distinguish, not garish
const LIGHTNESS  = 62;   // % — bright enough to glow on dark background
```

These values are chosen for the dark space background (`#01040a`). On very dark backgrounds, low-saturation colors disappear and high-lightness colors wash out. These constants may need minor tuning once rendered at actual canvas size — adjust together, not independently.

---

## Depth-based desaturation (optional enhancement)

Deeper subdomains can be slightly desaturated relative to their parent, encoding hierarchy in the color itself. A top-level domain is fully saturated; a third-level subdomain is slightly muted.

```javascript
function depthDesaturation(depth, baseSaturation) {
  // depth: 0 = top-level, 1 = one level down, etc.
  const desaturationPerLevel = 8; // % per level
  return Math.max(30, baseSaturation - depth * desaturationPerLevel);
}

// Usage:
const depth = domain.path.split('/').length - 1;
const saturation = depthDesaturation(depth, SATURATION);
const color = hslToHex(hue, saturation, LIGHTNESS);
```

This means `business` (depth 0) is fully saturated, `business/strategy` (depth 1) is slightly muted, and `business/strategy/marketing` (depth 2) is more muted. The visual effect: parent domains pop, leaf domains recede slightly — which matches their relative importance in the hierarchy.

This enhancement is optional for v1. If the corpus is shallow (2-3 levels), the effect is subtle. At 4+ levels it becomes meaningfully useful.

---

## Hue wheel allocation example

Given a corpus with three top-level domains:

```
business     → hue 0°    (red-pink family)
operations   → hue 120°  (green family)
technology   → hue 240°  (blue family)
```

Subdomains within `business` (assuming 5 subdomains):

```
business                              → hue 0°    (slot 0, offset 0°)
business/strategy                     → hue 22°   (slot 1, offset = 0.618 × 120° = 74°... mod sliceSize)
business/fundraising                  → hue 74°   (slot 2)
business/operations                   → hue 96°   (slot 3)
business/product_development          → hue 48°   (slot 4)
```

Each subdomain lands at a visually distinct point within the family's hue range, regardless of how many siblings there are.

At 10 subdomains the golden ratio ensures no two are perceptually adjacent. At 20 subdomains some hue proximity is unavoidable, but the distribution remains as spread as possible — which is the best any deterministic algorithm can do.

---

## Collision handling at scale

At very high subdomain counts (20+ per top-level), hue collisions become unavoidable within a slice. Two mitigations:

**1. Lightness alternation for near-collisions**
If two domains within the same top-level family would land within 8° of each other in hue, alternate their lightness by ±6%:

```javascript
function resolveCollisions(colorAssignments, threshold = 8) {
  const paths = Object.keys(colorAssignments);
  paths.forEach((path, i) => {
    const hue = hexToHsl(colorAssignments[path]).h;
    const nearNeighbors = paths.filter((other, j) => {
      if (i === j) return false;
      const otherHue = hexToHsl(colorAssignments[other]).h;
      return Math.abs(hue - otherHue) < threshold;
    });
    if (nearNeighbors.length > 0) {
      // Alternate lightness slightly
      const { h, s, l } = hexToHsl(colorAssignments[path]);
      const adjustment = (i % 2 === 0) ? 6 : -6;
      colorAssignments[path] = hslToHex(h, s, Math.max(45, Math.min(75, l + adjustment)));
    }
  });
  return colorAssignments;
}
```

**2. Expand top-level slice on demand**
If a top-level domain grows beyond 15 subdomains, it can be granted a larger slice at the cost of adjacent top-level domains. This requires re-running the color assignment — treat it as a corpus growth event that recomputes all colors. Since colors already change when new top-level domains are added, this is an expected behavior.

---

## When to recompute

Color assignment is computed once at viz initialization from the domain list. It does not change during a session.

Recompute when:
- A new top-level domain is discovered (`discover-subdomains` adds a root-level entry)
- This is a rare event — top-level domains represent major corpus categories

Do not recompute when:
- New subdomains are added within an existing top-level family — they just take the next slot
- New documents are added
- New entities are extracted

```javascript
// On viz load:
const domainColors = assignDomainColors(allDomains);
resolveCollisions(domainColors);

// Store on each domain node for use in rendering:
domains.forEach(d => {
  d.color = domainColors[d.path];
});
```

---

## Helper functions

```javascript
function hslToHex(h, s, l) {
  s /= 100; l /= 100;
  const a = s * Math.min(l, 1 - l);
  const f = n => {
    const k = (n + h / 30) % 12;
    const color = l - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
    return Math.round(255 * color).toString(16).padStart(2, '0');
  };
  return `#${f(0)}${f(8)}${f(4)}`;
}

function hexToHsl(hex) {
  let r = parseInt(hex.slice(1,3),16)/255;
  let g = parseInt(hex.slice(3,5),16)/255;
  let b = parseInt(hex.slice(5,7),16)/255;
  const max = Math.max(r,g,b), min = Math.min(r,g,b);
  let h, s, l = (max+min)/2;
  if (max === min) { h = s = 0; }
  else {
    const d = max - min;
    s = l > 0.5 ? d/(2-max-min) : d/(max+min);
    switch(max) {
      case r: h = ((g-b)/d + (g<b?6:0))/6; break;
      case g: h = ((b-r)/d + 2)/6; break;
      case b: h = ((r-g)/d + 4)/6; break;
    }
  }
  return { h: h*360, s: s*100, l: l*100 };
}
```

---

## Integration with existing viz

Replace the current color computation (wherever `region_colors` is generated or applied) with `assignDomainColors`. The output format is the same — a map of `domain_path → hex_color_string` — so the rest of the rendering pipeline is unchanged.

```javascript
// Before (current):
const color = hslColor(hashPath(domain.path));

// After:
const color = domainColors[domain.path]; // pre-computed at load
```

The `colorWithAlpha` helper from the nebula rendering spec already accepts hex strings, so no changes are needed there.

---

## What does NOT change

- Entity star colors — unchanged, still type-based
- Trade route colors — unchanged, still cyan
- Label typography and positioning — unchanged
- Physics, LOD, interaction — unchanged
- The nebula rendering spec (domain_nebula_spec) — the color it receives changes, but how it uses that color does not

---

## Design intent summary

The goal is a galaxy where you can glance at a cluster of nebulae and immediately see which ones are related (shared hue family) and which are from different parts of the corpus (different hue families), while still being able to tell individual domains apart within a family (golden ratio spacing). As the corpus grows, new domains automatically find visually sensible homes without any manual color curation. The system is self-organising.
