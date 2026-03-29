/**
 * Shared utilities — color, math, constants.
 */

export const TAU = Math.PI * 2;
export const PI = Math.PI;
export const { sin, cos, sqrt, abs, min, max, floor, round, random, pow, hypot, log } = Math;

export const WORLD_W = 5000;
export const WORLD_H = 5000;

// Zoom level thresholds
export const ZOOM_LEVELS = {
  galaxy: { max: 0.35 },
  sector: { min: 0.35, max: 0.75 },
  system: { min: 0.75, max: 1.50 },
  star:   { min: 1.50 },
};

export function getCurrentLevel(zoom) {
  if (zoom < ZOOM_LEVELS.galaxy.max) return 'galaxy';
  if (zoom < ZOOM_LEVELS.sector.max) return 'sector';
  if (zoom < ZOOM_LEVELS.system.max) return 'system';
  return 'star';
}

// Color utilities
export function hexRGB(hex) {
  if (!hex || hex[0] !== '#') return [128, 128, 128];
  return [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ];
}

export function rgba(r, g, b, a) {
  return `rgba(${r},${g},${b},${a})`;
}

export function colorAlpha(hex, alpha) {
  const [r, g, b] = hexRGB(hex);
  return rgba(r, g, b, alpha);
}

export function lighten(hex, amount) {
  const [r, g, b] = hexRGB(hex);
  return `rgb(${min(255, r + (255 - r) * amount)},${min(255, g + (255 - g) * amount)},${min(255, b + (255 - b) * amount)})`;
}

export function darken(hex, amount) {
  const [r, g, b] = hexRGB(hex);
  return `rgb(${max(0, r * (1 - amount))},${max(0, g * (1 - amount))},${max(0, b * (1 - amount))})`;
}

export function lerp(a, b, t) {
  return a + (b - a) * t;
}

export function clamp(v, lo, hi) {
  return min(hi, max(lo, v));
}

export function rnd(lo, hi) {
  return lo + random() * (hi - lo);
}

// Golden ratio color distribution
const GOLDEN_RATIO = 0.618033988749895;

export function assignDomainColors(domains) {
  const paths = domains.map(d => d.path);
  if (!paths.length) return {};

  // Find branching level
  const parts = paths.map(p => p.split('/'));
  let branchLevel = 0;
  for (let level = 0; level < Math.min(...parts.map(p => p.length)); level++) {
    const values = new Set(parts.map(p => p[level]));
    if (values.size > 1) break;
    branchLevel = level + 1;
  }

  // Group by branching segment
  const groups = {};
  for (const path of paths) {
    const segs = path.split('/');
    const key = segs.slice(0, branchLevel + 1).join('/');
    (groups[key] ??= []).push(path);
  }

  const groupKeys = Object.keys(groups).sort();
  const sliceSize = 360 / Math.max(groupKeys.length, 1);

  const colorMap = {};
  for (let gi = 0; gi < groupKeys.length; gi++) {
    const rangeStart = (gi / groupKeys.length) * 360;
    const family = groups[groupKeys[gi]].sort();
    for (let i = 0; i < family.length; i++) {
      const offset = ((i * GOLDEN_RATIO) % 1) * sliceSize;
      const hue = (rangeStart + offset) % 360;
      const depth = family[i].split('/').length - branchLevel;
      const sat = Math.max(30, 65 - depth * 8);
      colorMap[family[i]] = hslToHex(hue, sat, 62);
    }
  }
  return colorMap;
}

export function hslToHex(h, s, l) {
  s /= 100; l /= 100;
  const a = s * Math.min(l, 1 - l);
  const f = n => {
    const k = (n + h / 30) % 12;
    const color = l - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
    return Math.round(255 * color).toString(16).padStart(2, '0');
  };
  return `#${f(0)}${f(8)}${f(4)}`;
}

// Blend colors with dominant-biased weighting
export function blendColors(colors, weights) {
  let r = 0, g = 0, b = 0, tw = 0;
  const maxW = Math.max(...weights.filter(w => w > 0));
  colors.forEach((c, i) => {
    if (!c) return;
    const rgb = hexRGB(c);
    if (isNaN(rgb[0])) return;
    const w = Math.pow((weights[i] || 0) / (maxW || 1), 2) * (weights[i] || 0);
    r += rgb[0] * w; g += rgb[1] * w; b += rgb[2] * w; tw += w;
  });
  if (tw === 0) return '#888888';
  let rr = round(r / tw), gg = round(g / tw), bb = round(b / tw);
  const mx = Math.max(rr, gg, bb), mn = Math.min(rr, gg, bb);
  if (mx > 0 && mx - mn < 60) {
    const boost = 1.3;
    rr = min(255, round(rr === mx ? rr * boost : rr / boost + mn * 0.2));
    gg = min(255, round(gg === mx ? gg * boost : gg / boost + mn * 0.2));
    bb = min(255, round(bb === mx ? bb * boost : bb / boost + mn * 0.2));
  }
  return `rgb(${rr},${gg},${bb})`;
}
