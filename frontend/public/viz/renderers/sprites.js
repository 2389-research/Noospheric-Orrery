// Offscreen sprite cache for node glows.
//
// Rendering a soft glow (multi-stop radial gradients, and especially shadowBlur —
// a Gaussian blur per fill) is expensive. Doing it once per (color/kind) into an
// offscreen canvas and then drawImage()-ing that bitmap per node every frame is
// dramatically cheaper: the blur/gradient work happens once, and drawImage of a
// cached bitmap is one of the fastest Canvas2D ops. Crucially this PRESERVES the
// look — shadowBlur included — because we bake the exact same drawing into the
// sprite; we just stop paying for it 60×/second × thousands of nodes.
//
// Sprites are rendered at a canonical size and scaled per node via drawImage's
// destination rect; per-node brightness is applied with globalAlpha at draw time.
// Glows are inherently soft, so the slight upscaling when a node is large/zoomed
// is invisible.

import { rgba, hexRGB, canonicalHex, TAU, PI, min, sin, cos, clamp } from '../core/utils.js';

const _cache = new Map();

// Bounded, because the keys are not a closed set: entity colors are BLENDED per entity
// from its domain mix, so a large graph can mint thousands of distinct colors, and each
// sprite is a retained offscreen canvas (ENTITY_PX² × 4 bytes ≈ 65 KB at 128px). Left
// unbounded that is tens of MB of canvases that are never released.
//
// A Map iterates in insertion order, so the first key is the oldest; re-inserting on hit
// makes that least-recently-USED rather than merely oldest, which matters because the
// working set is whatever is currently on screen.
const _CACHE_MAX = 256;

/** Return a cached offscreen canvas for `key`, rendering it via `render(cx, size)`
 *  on first request. `size` is the sprite's pixel dimension (square); the glow is
 *  centered at size/2. */
export function getSprite(key, size, render) {
  const cv = _cache.get(key);
  if (cv) {
    _cache.delete(key); _cache.set(key, cv);   // mark most-recently-used
    return cv;
  }
  const made = document.createElement('canvas');
  made.width = made.height = size;
  render(made.getContext('2d'), size);
  _cache.set(key, made);
  if (_cache.size > _CACHE_MAX) _cache.delete(_cache.keys().next().value);
  return made;
}

// ---- Entity glow ---------------------------------------------------------------
// The 4-layer entity glow from drawEntityStars, minus the tiny hot core (kept as a
// crisp direct draw). Canonical radius BR0; the halo reaches 5×BR0, so the sprite
// must span 10×BR0. Baked at per-entity alpha = 1 (constant coefficients only);
// the caller applies the real alpha with globalAlpha and scales by bR/ENTITY_BR0.
export const ENTITY_BR0 = 12;
// Sector-zoom brightness multiplier. Shared with galaxy.js: the sprite bakes it
// into the halo/glow, and the core (drawn live there) uses the same value — so
// the halo↔core brightness ratio can't drift.
export const SECTOR_BRIGHT = 1.3;
const ENTITY_PX = ENTITY_BR0 * 10 + 8; // 128, small margin for the outermost stop

export function entityGlowSprite(color) {
  // Key on the canonical hex, not the raw string: entity colors arrive as blended
  // `rgb(r,g,b)` and domain/leaf colors as `#rrggbb`, so the same color by two routes
  // used to bake two sprites. Quantized to 4 levels per channel first — blended colors
  // are continuous, so without it nearly every multi-domain entity mints its own sprite
  // and thrashes the cache; a 4-unit step is imperceptible on a soft glow.
  const [r0, g0, b0] = hexRGB(color);
  const q = v => Math.round(v / 4) * 4;
  const key = canonicalHex(`rgb(${q(r0)},${q(g0)},${q(b0)})`);
  return getSprite('e:' + key, ENTITY_PX, (cx, S) => {
    const c = S / 2, bR = ENTITY_BR0, sectorBright = SECTOR_BRIGHT;
    const [r, g, b] = hexRGB(key);
    const disc = (radius, stops) => {
      const grad = cx.createRadialGradient(c, c, 0, c, c, radius);
      for (const [at, a] of stops) grad.addColorStop(at, rgba(r, g, b, a));
      cx.fillStyle = grad;
      cx.beginPath(); cx.arc(c, c, radius, 0, TAU); cx.fill();
    };
    // Layer 1: wide outer halo
    const haloA = 0.08 * sectorBright;
    disc(bR * 5, [[0, haloA], [0.4, haloA * 0.3], [1, 0]]);
    // Layer 2: inner glow
    const innerA = 0.28 * sectorBright;
    disc(bR * 2.5, [[0, innerA], [0.5, innerA * 0.4], [1, 0]]);
    // Layer 3: color bloom
    const bloomA = sectorBright;
    disc(bR * 1.0, [[0, 0.9 * bloomA], [0.3, 0.5 * bloomA], [0.7, 0.1 * bloomA], [1, 0]]);
  });
}

// ---- Repo core (gold, shadowBlur) ---------------------------------------------
// The bright gold-white repo core with its shadowBlur halo — the expensive part of
// drawCollections. Baked once at canonical coreR0; the caller scales by coreR/REPO_CORE0
// and applies the breathing pulse via globalAlpha. Spikes/halo/label stay direct.
export const REPO_CORE0 = 8;
const REPO_BLUR = REPO_CORE0 * 2;
const REPO_PX = Math.ceil((REPO_CORE0 + REPO_BLUR) * 2 + 8); // fits core + blur spread

export function repoCoreSprite(color) {
  return getSprite('repo-core:' + color, REPO_PX, (cx, S) => {
    const c = S / 2, coreR = REPO_CORE0;
    const [r, g, b] = hexRGB(color);
    cx.shadowBlur = REPO_BLUR;
    cx.shadowColor = 'rgba(255,230,170,0.4)';
    const sg = cx.createRadialGradient(c, c, 0, c, c, coreR);
    sg.addColorStop(0, 'rgba(255,240,210,1)');
    sg.addColorStop(0.4, rgba(r, g, b, 0.85));
    sg.addColorStop(1, rgba(r, g, b, 0));
    cx.fillStyle = sg;
    cx.beginPath(); cx.arc(c, c, coreR, 0, TAU); cx.fill();
    cx.shadowBlur = 0;
  });
}

// ---- Domain nebula ------------------------------------------------------------
// The single most expensive per-frame cost in the galaxy/sector zoom band: every
// on-screen domain rebuilt 4 offset cloud gradients + a wide halo + a shadowBlur
// star-point + 4 spike gradients EVERY frame. That's fine when domains are tiny
// (zoomed out) or mostly culled (zoomed in), but in the middle band they're large
// AND on-screen, so the fill/blur cost peaks and FPS drops (the "strobe"/judder).
//
// Bake all of that once per (color, state, maturity-bucket) — exactly as the entity
// and repo glows are cached — and drawImage it. The animated/cheap bits (breathing,
// simmering flicker, activity/hover rings, labels) stay direct in galaxy.js.
//
// Baked at a fixed reference brightness NEB_BAKE (so zoomed-in domains can reach it);
// the caller applies the real per-frame brightness via globalAlpha = brightness/NEB_BAKE.
// rot=0 and breathe=1 are baked in — the rotation is ~0.0003 rad/frame (imperceptible)
// and the breathing pulse is ±6% (dropped; also imperceptible on a soft nebula).
// Canonical bake radius. Non-subdomain radii are 120 + sqrt(docCount)*35 (usually
// >120), so baking at 130 keeps typical domains at/under 1× (crisp star-point +
// spikes) instead of upscaling and softening them; only the largest domains upscale,
// and their soft clouds tolerate it. Bounded so per-(color,state,maturity) sprites
// stay small enough to cache many without bloating memory on a weak GPU.
export const DOM_BR0 = 130;        // canonical nebula radius the sprite is baked at
export const NEB_BAKE = 1.4;       // reference brightness baked in (see above)
const DOM_PX = Math.ceil(DOM_BR0 * 4.2 + 24);  // spans the outer cloud (~2×bR) both sides

// Bucket continuous maturity so the cache stays small (a handful of buckets ×
// a small color palette). Unformed/simmering ignore maturity.
function _matBucket(maturity) { return Math.max(0.25, Math.round(clamp(maturity, 0, 1) * 4) / 4); }

export function domainNebulaSprite(color, state, maturity) {
  const mb = state === 'formed' ? _matBucket(maturity) : 0;
  return getSprite(`dom:${state}:${color}:${mb}`, DOM_PX, (cx, S) => {
    const c = S / 2, bR = DOM_BR0, B = NEB_BAKE;
    const [r, g, b] = hexRGB(color);

    if (state === 'unformed') {
      for (let i = 0; i < 4; i++) {
        const angle = i * 1.4;                       // rot=0
        const lr = bR * (2.0 - i * 0.15);
        const ox = cos(angle) * bR * 0.12, oy = sin(angle) * bR * 0.08;
        const a = (0.022 - i * 0.004) * B;
        const gr = cx.createRadialGradient(c + ox, c + oy, 0, c + ox, c + oy, lr);
        gr.addColorStop(0, rgba(r, g, b, a * 2));
        gr.addColorStop(0.4, rgba(r, g, b, a));
        gr.addColorStop(1, rgba(r, g, b, 0));
        cx.fillStyle = gr; cx.beginPath(); cx.arc(c + ox, c + oy, lr, 0, TAU); cx.fill();
      }
      return;
    }

    if (state === 'simmering') {
      // Only the cloud layers bake; the amber cocoon + flickering core animate and
      // stay direct in galaxy.js (there are only a handful of simmering domains).
      for (let i = 0; i < 4; i++) {
        const angle = i * 1.4;
        const lr = bR * (1.8 - i * 0.10);
        const ox = cos(angle) * bR * 0.10, oy = sin(angle) * bR * 0.08;
        const a = (0.035 - i * 0.005) * B;
        const gr = cx.createRadialGradient(c + ox, c + oy, 0, c + ox, c + oy, lr);
        gr.addColorStop(0, rgba(r, g, b, a * 2));
        gr.addColorStop(0.5, rgba(r, g, b, a));
        gr.addColorStop(1, rgba(r, g, b, 0));
        cx.fillStyle = gr; cx.beginPath(); cx.arc(c + ox, c + oy, lr, 0, TAU); cx.fill();
      }
      return;
    }

    // formed
    const maturity_ = mb;
    const bright = (0.5 + maturity_ * 0.5) * B;
    const coreR = bR * (0.12 + maturity_ * 0.08);
    // Cloud with inner clearing
    for (let i = 0; i < 4; i++) {
      const angle = i * 1.4;
      const lr = bR * (2.0 - i * 0.12);
      const ox = cos(angle) * bR * 0.07, oy = sin(angle) * bR * 0.06;
      const baseA = (0.045 + maturity_ * 0.02 - i * 0.005) * B;
      const gr = cx.createRadialGradient(c + ox, c + oy, bR * 0.2, c + ox, c + oy, lr);
      gr.addColorStop(0, rgba(r, g, b, 0));
      gr.addColorStop(0.12, rgba(r, g, b, baseA * 1.8));
      gr.addColorStop(0.5, rgba(r, g, b, baseA));
      gr.addColorStop(1, rgba(r, g, b, 0));
      cx.fillStyle = gr; cx.beginPath(); cx.arc(c + ox, c + oy, lr, 0, TAU); cx.fill();
    }
    // Wide halo
    const wh = cx.createRadialGradient(c, c, 0, c, c, bR * 0.8);
    wh.addColorStop(0, rgba(r, g, b, 0.15 * bright));
    wh.addColorStop(0.3, rgba(r, g, b, 0.06 * bright));
    wh.addColorStop(1, rgba(r, g, b, 0));
    cx.fillStyle = wh; cx.beginPath(); cx.arc(c, c, bR * 0.8, 0, TAU); cx.fill();
    // Star point (the expensive shadowBlur — baked once here)
    cx.shadowBlur = coreR * 2;
    cx.shadowColor = `rgba(255,255,255,${0.3 * bright})`;
    const sg = cx.createRadialGradient(c, c, 0, c, c, coreR);
    sg.addColorStop(0, `rgba(255,255,255,${min(1.0, bright)})`);
    sg.addColorStop(0.4, rgba(r, g, b, 0.8 * bright));
    sg.addColorStop(1, rgba(r, g, b, 0));
    cx.fillStyle = sg; cx.beginPath(); cx.arc(c, c, coreR, 0, TAU); cx.fill();
    cx.shadowBlur = 0;
    // Spikes
    const spikeLen = bR * (0.5 + maturity_ * 1.5), spikeA = bright * 0.35;
    for (let s = 0; s < 4; s++) {
      const a = s * PI / 2;
      const x2 = c + cos(a) * spikeLen, y2 = c + sin(a) * spikeLen;
      const spg = cx.createLinearGradient(c, c, x2, y2);
      spg.addColorStop(0, `rgba(255,255,255,${spikeA})`);
      spg.addColorStop(0.3, rgba(r, g, b, spikeA * 0.5));
      spg.addColorStop(1, rgba(r, g, b, 0));
      cx.strokeStyle = spg; cx.lineWidth = 2;
      cx.beginPath(); cx.moveTo(c, c); cx.lineTo(x2, y2); cx.stroke();
    }
  });
}

// ---- Star-view glyphs (docs + co-entities) ------------------------------------
// The entity star view drew one/two radial gradients PER document and PER co-entity
// EVERY frame (renderers/star.js) — the same un-cached cost the galaxy already
// eliminated. Bake the amber doc glow (one sprite, constant color) and the
// per-type co-entity glow+core (one sprite per color) and drawImage them, scaled
// by node radius and modulated by per-node alpha via globalAlpha. Baked at alpha=1
// (the constant coefficients only); the crisp cores/icons/labels stay direct.

export const DOC_R0 = 8;                        // canonical doc radius the sprite is baked at
const DOC_PX = Math.ceil(DOC_R0 * 2.5 * 2 + 8); // glow spans 2.5×r both sides

export function docGlowSprite() {
  return getSprite('doc-glow', DOC_PX, (cx, S) => {
    const c = S / 2, sz = DOC_R0;
    const g = cx.createRadialGradient(c, c, 0, c, c, sz * 2.5);
    g.addColorStop(0, 'rgba(255,200,120,0.20)');
    g.addColorStop(0.5, 'rgba(200,150,80,0.08)');
    g.addColorStop(1, 'rgba(180,120,60,0)');
    cx.fillStyle = g;
    cx.beginPath(); cx.arc(c, c, sz * 2.5, 0, TAU); cx.fill();
  });
}

export const CO_R0 = 6;                          // canonical co-entity radius
const CO_PX = Math.ceil(CO_R0 * 3 * 2 + 8);      // glow spans 3×r both sides

export function coEntityGlowSprite(color) {
  return getSprite('co:' + color, CO_PX, (cx, S) => {
    const c = S / 2, rad = CO_R0;
    const [r, g, b] = hexRGB(color);
    // Outer glow
    const gg = cx.createRadialGradient(c, c, 0, c, c, rad * 3);
    gg.addColorStop(0, rgba(r, g, b, 0.2));
    gg.addColorStop(0.5, rgba(r, g, b, 0.06));
    gg.addColorStop(1, rgba(r, g, b, 0));
    cx.fillStyle = gg;
    cx.beginPath(); cx.arc(c, c, rad * 3, 0, TAU); cx.fill();
    // Hot core (white → color)
    const cg = cx.createRadialGradient(c, c, 0, c, c, rad * 0.5);
    cg.addColorStop(0, 'rgba(255,255,255,0.8)');
    cg.addColorStop(0.5, rgba(r, g, b, 0.7));
    cg.addColorStop(1, rgba(r, g, b, 0));
    cx.fillStyle = cg;
    cx.beginPath(); cx.arc(c, c, rad * 0.5, 0, TAU); cx.fill();
  });
}
