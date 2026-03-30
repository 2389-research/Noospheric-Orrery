/**
 * Galaxy View renderer — cluster clouds + domain nebulae + faint routes.
 * Renders at zoom < 0.35
 */

import { sin, cos, TAU, PI, hexRGB, rgba, colorAlpha, clamp, min, max } from '../core/utils.js';

/** Draw the background starfield + nebula clouds */
export function drawBackground(ctx, W, H, tick) {
  // Deep space gradient
  const g = ctx.createRadialGradient(W/2, H/2, 0, W/2, H/2, max(W, H) * 0.7);
  g.addColorStop(0, '#060d22');
  g.addColorStop(1, '#01040a');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);

  // Background stars (screen space)
  if (!drawBackground._stars) {
    drawBackground._stars = Array.from({length: 500}, () => ({
      x: Math.random(), y: Math.random(),
      r: Math.pow(Math.random(), 3) * 1.6 + 0.1,
      a: Math.random() * 0.4 + 0.05,
      phase: Math.random() * TAU,
      speed: (Math.random() * 0.3 + 0.05) * (Math.random() < 0.5 ? 1 : -1),
    }));
  }

  for (const s of drawBackground._stars) {
    const tw = 0.5 + 0.5 * sin(tick * 0.004 * s.speed + s.phase);
    ctx.globalAlpha = s.a * tw;
    ctx.fillStyle = '#fff';
    ctx.beginPath();
    ctx.arc(s.x * W, s.y * H, s.r, 0, TAU);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
}

/** Draw a cluster composite cloud */
export function drawClusterCloud(ctx, cluster, state) {
  const { centroidX: cx, centroidY: cy, radius: r } = cluster;

  // Composite glow from member domain colors
  for (const dom of cluster.members) {
    const [dr, dg, db] = hexRGB(dom.color);
    const a = 0.015 * clamp(dom.birthScale, 0, 1);
    const gr = ctx.createRadialGradient(dom.x, dom.y, 0, dom.x, dom.y, r * 0.6);
    gr.addColorStop(0, rgba(dr, dg, db, a * 2));
    gr.addColorStop(0.5, rgba(dr, dg, db, a));
    gr.addColorStop(1, rgba(dr, dg, db, 0));
    ctx.fillStyle = gr;
    ctx.beginPath();
    ctx.arc(dom.x, dom.y, r * 0.6, 0, TAU);
    ctx.fill();
  }
}

/** Draw a domain nebula (3 states: unformed, simmering, formed) */
export function drawDomainNebula(ctx, dom, tick, camera, neighborhood) {
  const [r, g, b] = hexRGB(dom.color);
  const bR = dom.radius * clamp(dom.birthScale, 0, 1);
  const act = dom.activityGlow;
  const zoomBright = camera ? clamp((camera.zoom - 0.18) / 0.4, 0, 0.6) : 0;
  // Dim non-neighborhood domains when something is selected
  const hasNb = neighborhood && neighborhood.size > 0;
  const dimFactor = hasNb && !neighborhood.has(dom.id) ? 0.3 : 1.0;
  const brightness = (1 + act * 2.2 + zoomBright) * dimFactor;

  if (dom.simmering) {
    _drawSimmering(ctx, dom, bR, r, g, b, tick, brightness);
  } else if (dom.maturity > 0) {
    _drawFormed(ctx, dom, bR, r, g, b, tick, brightness);
  } else {
    _drawUnformed(ctx, dom, bR, r, g, b, tick, brightness);
  }

  // Activity ring — visible when domain is hit by a pulse
  if (act > 0.25) {
    const ringR = bR * (0.9 + act * 0.6);
    ctx.strokeStyle = rgba(r, g, b, act * 0.45);
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    ctx.arc(dom.x, dom.y, ringR, 0, TAU);
    ctx.stroke();
  }

  // Hover/selected ring — dashed outline so you know you're on one
  const isActive = dom.id === dom._hoveredId || dom.id === dom._pinnedId;
  if (isActive) {
    ctx.strokeStyle = rgba(r, g, b, 0.35);
    ctx.lineWidth = 1.5;
    ctx.setLineDash([6, 10]);
    ctx.beginPath();
    ctx.arc(dom.x, dom.y, bR * 1.4, 0, TAU);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // Label — closer to core so it's clear what it belongs to
  const labelA = 0.2 + act * 0.6 + (dom.maturity > 0 ? 0.1 : 0);
  const labelY = dom.y + bR * 1.1 + 12;
  ctx.fillStyle = rgba(r, g, b, min(1, labelA + 0.7));
  ctx.font = `${dom.isSubdomain ? 28 : 36}px 'Courier New', monospace`;
  ctx.textAlign = 'center';
  ctx.fillText(dom.label.split('/').pop(), dom.x, labelY);
  ctx.fillStyle = rgba(r, g, b, 0.4);
  ctx.font = "24px 'Courier New', monospace";
  ctx.fillText(`${dom.docCount} docs`, dom.x, labelY + 30);
}

/** Compute neighborhood set for an active node */
export function getNeighborhood(state) {
  const activeId = state.pinnedId ?? state.hoveredId;
  if (!activeId) return null;

  const ids = new Set([activeId]);

  // Find active node
  let activeNode = null;
  for (const [, e] of state.entities) {
    if (e.id === activeId) { activeNode = e; break; }
  }
  if (!activeNode) {
    for (const [, d] of state.domains) {
      if (d.id === activeId) { activeNode = d; break; }
    }
  }
  if (!activeNode) return null;

  if (activeNode.kind === 'entity') {
    // Entity selected: neighborhood = its parent domains only
    const dw = activeNode.domainWeights || {};
    for (const path of Object.keys(dw)) {
      const dom = state.domains.get(path);
      if (dom) ids.add(dom.id);
    }
  } else if (activeNode.kind === 'domain') {
    // Add ALL entities in this domain — brightening shows the domain's reach
    for (const [, e] of state.entities) {
      if (e.domainWeights?.[activeNode.path]) ids.add(e.id);
    }
  }

  return ids;
}

/** Draw neighborhood highlight lines when entity/domain is selected. */
export function drawNeighborhoodLines(ctx, state, camera) {
  const activeId = state.pinnedId ?? state.hoveredId;
  if (!activeId) return;

  let activeNode = null;
  for (const [, e] of state.entities) {
    if (e.id === activeId) { activeNode = e; break; }
  }
  if (!activeNode) {
    for (const [, d] of state.domains) {
      if (d.id === activeId) { activeNode = d; break; }
    }
  }
  if (!activeNode) return;

  if (activeNode.kind === 'entity') {
    const dw = activeNode.domainWeights || {};

    // Lines to parent domains only — entity↔entity belongs in star view
    for (const [path] of Object.entries(dw)) {
      const dom = state.domains.get(path);
      if (!dom) continue;
      ctx.strokeStyle = rgba(100, 160, 220, 0.3);
      ctx.lineWidth = 0.8;
      ctx.beginPath();
      ctx.moveTo(activeNode.x, activeNode.y);
      ctx.lineTo(dom.x, dom.y);
      ctx.stroke();
    }
  } else if (activeNode.kind === 'domain') {
    // Lines to ALL entities in this domain — subtle since there are many
    for (const [, e] of state.entities) {
      if (!e.domainWeights?.[activeNode.path]) continue;
      ctx.strokeStyle = rgba(100, 160, 220, 0.15);
      ctx.lineWidth = 0.4;
      ctx.beginPath();
      ctx.moveTo(activeNode.x, activeNode.y);
      ctx.lineTo(e.x, e.y);
      ctx.stroke();
    }
  }
}

/** Draw sector-level metadata for a domain (only at zoom > 0.35) */
export function drawDomainSectorDetail(ctx, dom) {
  const [r, g, b] = hexRGB(dom.color);
  const bR = dom.radius * clamp(dom.birthScale, 0, 1);

  // Spec version + entity count
  const specStr = dom.maturity > 0 ? `spec v${dom.specVersion || '?'}` : 'no spec';
  const meta = `${specStr} · ${dom.entityCount || '?'} entities`;
  const labelY = dom.y + bR * 1.1 + 42;
  ctx.fillStyle = rgba(r, g, b, 0.3);
  ctx.font = "20px 'Courier New', monospace";
  ctx.textAlign = 'center';
  ctx.fillText(meta, dom.x, labelY + 30);
}

function _drawUnformed(ctx, dom, bR, r, g, b, tick, brightness) {
  for (let i = 0; i < 4; i++) {
    const angle = dom.rot * (1 - i * 0.15) + i * 1.4;
    const lr = bR * (2.0 - i * 0.15);
    const ox = cos(angle) * bR * 0.12, oy = sin(angle) * bR * 0.08;
    const a = (0.022 - i * 0.004) * clamp(dom.birthScale, 0, 1) * brightness;
    const gr = ctx.createRadialGradient(dom.x + ox, dom.y + oy, 0, dom.x + ox, dom.y + oy, lr);
    gr.addColorStop(0, rgba(r, g, b, a * 2));
    gr.addColorStop(0.4, rgba(r, g, b, a));
    gr.addColorStop(1, rgba(r, g, b, 0));
    ctx.fillStyle = gr;
    ctx.beginPath();
    ctx.arc(dom.x + ox, dom.y + oy, lr, 0, TAU);
    ctx.fill();
  }
}

function _drawSimmering(ctx, dom, bR, r, g, b, tick, brightness) {
  // Cloud layers
  for (let i = 0; i < 4; i++) {
    const angle = dom.rot * (1 - i * 0.15) + i * 1.4;
    const lr = bR * (1.8 - i * 0.10);
    const ox = cos(angle) * bR * 0.10, oy = sin(angle) * bR * 0.08;
    const a = (0.035 - i * 0.005) * clamp(dom.birthScale, 0, 1) * brightness;
    const gr = ctx.createRadialGradient(dom.x + ox, dom.y + oy, 0, dom.x + ox, dom.y + oy, lr);
    gr.addColorStop(0, rgba(r, g, b, a * 2));
    gr.addColorStop(0.5, rgba(r, g, b, a));
    gr.addColorStop(1, rgba(r, g, b, 0));
    ctx.fillStyle = gr;
    ctx.beginPath();
    ctx.arc(dom.x + ox, dom.y + oy, lr, 0, TAU);
    ctx.fill();
  }

  // Amber cocoon
  const pulse = 0.7 + 0.3 * sin(tick * 0.003);
  const cocoon = ctx.createRadialGradient(dom.x, dom.y, 0, dom.x, dom.y, bR * 0.55);
  cocoon.addColorStop(0, `rgba(255,160,60,${0.10 * pulse * brightness})`);
  cocoon.addColorStop(0.5, `rgba(220,100,30,${0.05 * pulse * brightness})`);
  cocoon.addColorStop(1, 'rgba(180,60,10,0)');
  ctx.fillStyle = cocoon;
  ctx.beginPath();
  ctx.arc(dom.x, dom.y, bR * 0.55, 0, TAU);
  ctx.fill();

  // Flickering core
  const flicker = 0.5 + 0.5 * sin(tick * 0.007 + sin(tick * 0.013));
  const coreR = bR * 0.09 * (0.8 + 0.2 * flicker);
  const core = ctx.createRadialGradient(dom.x, dom.y, 0, dom.x, dom.y, coreR);
  core.addColorStop(0, `rgba(255,240,200,${0.65 * flicker})`);
  core.addColorStop(0.5, `rgba(255,180,80,${0.40 * flicker})`);
  core.addColorStop(1, 'rgba(255,120,40,0)');
  ctx.fillStyle = core;
  ctx.beginPath();
  ctx.arc(dom.x, dom.y, coreR, 0, TAU);
  ctx.fill();
}

function _drawFormed(ctx, dom, bR, r, g, b, tick, brightness) {
  const maturity = dom.maturity;
  const bright = (0.5 + maturity * 0.5) * brightness;
  const coreR = bR * (0.12 + maturity * 0.08);
  const breathe = 0.94 + 0.06 * sin(tick * 0.001);

  // Cloud with inner clearing
  for (let i = 0; i < 4; i++) {
    const angle = dom.rot * (1 - i * 0.15) + i * 1.4;
    const lr = bR * (2.0 - i * 0.12);
    const ox = cos(angle) * bR * 0.07, oy = sin(angle) * bR * 0.06;
    const baseA = (0.045 + maturity * 0.02 - i * 0.005) * clamp(dom.birthScale, 0, 1) * brightness;
    const gr = ctx.createRadialGradient(dom.x + ox, dom.y + oy, bR * 0.2, dom.x + ox, dom.y + oy, lr);
    gr.addColorStop(0, rgba(r, g, b, 0));
    gr.addColorStop(0.12, rgba(r, g, b, baseA * 1.8));
    gr.addColorStop(0.5, rgba(r, g, b, baseA));
    gr.addColorStop(1, rgba(r, g, b, 0));
    ctx.fillStyle = gr;
    ctx.beginPath();
    ctx.arc(dom.x + ox, dom.y + oy, lr, 0, TAU);
    ctx.fill();
  }

  // Wide halo
  const wh = ctx.createRadialGradient(dom.x, dom.y, 0, dom.x, dom.y, bR * 0.8);
  wh.addColorStop(0, rgba(r, g, b, 0.15 * bright));
  wh.addColorStop(0.3, rgba(r, g, b, 0.06 * bright));
  wh.addColorStop(1, rgba(r, g, b, 0));
  ctx.fillStyle = wh;
  ctx.beginPath();
  ctx.arc(dom.x, dom.y, bR * 0.8, 0, TAU);
  ctx.fill();

  // Star point
  ctx.shadowBlur = coreR * 2;
  ctx.shadowColor = `rgba(255,255,255,${0.3 * bright})`;
  const sg = ctx.createRadialGradient(dom.x, dom.y, 0, dom.x, dom.y, coreR);
  sg.addColorStop(0, `rgba(255,255,255,${min(1.0, bright * breathe)})`);
  sg.addColorStop(0.4, rgba(r, g, b, 0.8 * bright));
  sg.addColorStop(1, rgba(r, g, b, 0));
  ctx.fillStyle = sg;
  ctx.beginPath();
  ctx.arc(dom.x, dom.y, coreR, 0, TAU);
  ctx.fill();
  ctx.shadowBlur = 0;

  // Spikes
  const spikeLen = bR * (0.5 + maturity * 1.5);
  const spikeA = bright * 0.35 * breathe;
  for (let s = 0; s < 4; s++) {
    const a = s * PI / 2;
    const x2 = dom.x + cos(a) * spikeLen, y2 = dom.y + sin(a) * spikeLen;
    const spg = ctx.createLinearGradient(dom.x, dom.y, x2, y2);
    spg.addColorStop(0, `rgba(255,255,255,${spikeA})`);
    spg.addColorStop(0.3, rgba(r, g, b, spikeA * 0.5));
    spg.addColorStop(1, rgba(r, g, b, 0));
    ctx.strokeStyle = spg;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(dom.x, dom.y);
    ctx.lineTo(x2, y2);
    ctx.stroke();
  }
}

/** Draw trade routes + traveling pulses — only visible at sector zoom */
export function drawTradeRoutes(ctx, state, camera) {
  // Routes fade in starting at zoom 0.35, fully visible at 0.55
  const routeAlpha = camera ? clamp((camera.zoom - 0.35) / 0.2, 0, 1) : 1;
  if (routeAlpha <= 0 && !state.pulses.length) return;

  const maxWeight = Math.max(1, ...state.tradeRoutes.map(r => r.weight));

  // Draw route lines
  for (const route of state.tradeRoutes) {
    const srcDom = state.domains.get(route.source);
    const tgtDom = state.domains.get(route.target);
    if (!srcDom || !tgtDom) continue;

    const normWeight = route.weight / maxWeight;
    const a = (0.06 + normWeight * 0.12) * routeAlpha;
    const lw = (0.6 + normWeight * 1.5) * routeAlpha;
    if (a < 0.01) continue;

    ctx.setLineDash([8, 16]);
    ctx.strokeStyle = rgba(0, 200, 180, a);
    ctx.lineWidth = lw;
    ctx.beginPath();
    ctx.moveTo(srcDom.x, srcDom.y);
    ctx.lineTo(tgtDom.x, tgtDom.y);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // Draw traveling pulses (from state.pulses)
  for (const p of state.pulses) {
    const srcDom = state.domains.get(p.source);
    const tgtDom = state.domains.get(p.target);
    if (!srcDom || !tgtDom) continue;

    const rawP = p.progress;
    // Ease in-out
    const ep = rawP < 0.5 ? 2 * rawP * rawP : -1 + (4 - 2 * rawP) * rawP;
    // Sine brightness envelope
    const gf = sin(rawP * Math.PI);

    const ax = srcDom.x, ay = srcDom.y;
    const bx = tgtDom.x, by = tgtDom.y;
    const px = ax + (bx - ax) * ep;
    const py = ay + (by - ay) * ep;

    // Trail — white gradient behind the dot
    const trailP = max(0, rawP - 0.10);
    const tep = trailP < 0.5 ? 2 * trailP * trailP : -1 + (4 - 2 * trailP) * trailP;
    const tx = ax + (bx - ax) * tep;
    const ty = ay + (by - ay) * tep;
    const tg = ctx.createLinearGradient(tx, ty, px, py);
    tg.addColorStop(0, `rgba(255,255,255,0)`);
    tg.addColorStop(1, `rgba(255,255,255,${0.50 * gf})`);
    ctx.strokeStyle = tg;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(tx, ty);
    ctx.lineTo(px, py);
    ctx.stroke();

    // Dot — white core → domain color
    const [pr, pg, pb] = p.col;
    const sz = 20 + gf * 12; // world units
    const dg = ctx.createRadialGradient(px, py, 0, px, py, sz);
    dg.addColorStop(0, `rgba(255,255,255,${0.98 * gf})`);
    dg.addColorStop(0.2, `rgba(${pr},${pg},${pb},${0.85 * gf})`);
    dg.addColorStop(0.6, `rgba(${pr},${pg},${pb},${0.30 * gf})`);
    dg.addColorStop(1, `rgba(${pr},${pg},${pb},0)`);
    ctx.fillStyle = dg;
    ctx.beginPath();
    ctx.arc(px, py, sz, 0, TAU);
    ctx.fill();

    // Arrival ripple at destination (last 18% of travel)
    if (rawP > 0.82) {
      const rp = (rawP - 0.82) / 0.18;
      const rippleR = tgtDom.radius * (0.2 + rp * 0.7);
      const rippleA = (1 - rp) * 0.55;
      ctx.strokeStyle = `rgba(255,255,255,${rippleA})`;
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      ctx.arc(tgtDom.x, tgtDom.y, rippleR, 0, TAU);
      ctx.stroke();
    }
  }
}

/** Draw entity stars — LOD based on zoom, viewport culling, neighborhood highlight */
export function drawEntityStars(ctx, state, camera, W, H, neighborhood) {
  const hasNeighborhood = neighborhood && neighborhood.size > 0;
  const galaxyZoom = camera.zoom < 0.35;

  // At galaxy zoom with no selection, don't render entities
  if (galaxyZoom && !hasNeighborhood) return;

  const sectorZoom = camera.zoom >= 0.5;
  const deepZoom = camera.zoom >= 0.75;

  // Viewport culling
  const margin = 200 / camera.zoom;
  const viewLeft = camera.x - W / 2 / camera.zoom - margin;
  const viewRight = camera.x + W / 2 / camera.zoom + margin;
  const viewTop = camera.y - H / 2 / camera.zoom - margin;
  const viewBottom = camera.y + H / 2 / camera.zoom + margin;

  const minSource = deepZoom ? 1 : sectorZoom ? 3 : 5;
  const zoomScale = clamp((camera.zoom - 0.3) / 0.5, 0, 1);

  for (const [, e] of state.entities) {
    if (e.birthScale < 0.1) continue;

    const inNeighborhood = hasNeighborhood && neighborhood.has(e.id);

    // LOD filter — but always render neighborhood members
    if (!inNeighborhood) {
      if (galaxyZoom) continue;
      if (e.sourceCount < minSource && e.activityGlow < 0.1) continue;
      if (e.x < viewLeft || e.x > viewRight || e.y < viewTop || e.y > viewBottom) continue;
    }

    // Dim non-neighborhood when something is selected, brighten members
    const dimFactor = hasNeighborhood && !inNeighborhood ? 0.15 : 1.0;
    const brightFactor = inNeighborhood ? 1.3 : 1.0;

    const act = e.activityGlow;
    const sizeBoost = (1 + zoomScale * 1.5) * brightFactor;
    const bR = (e.radius * 0.6 + act * 3) * e.birthScale * sizeBoost;
    const [r, g, b] = hexRGB(e.color);
    const alpha = clamp((0.3 + act * 0.7 + zoomScale * 0.3) * dimFactor * brightFactor, 0, 1);

    if (sectorZoom) {
      // Multi-layer glow at sector zoom — 30% brighter than galaxy
      const sectorBright = 1.3;

      // Layer 1: wide outer halo
      const haloR = bR * 5;
      const haloA = 0.08 * alpha * dimFactor * sectorBright;
      const g1 = ctx.createRadialGradient(e.x, e.y, 0, e.x, e.y, haloR);
      g1.addColorStop(0, rgba(r, g, b, haloA));
      g1.addColorStop(0.4, rgba(r, g, b, haloA * 0.3));
      g1.addColorStop(1, rgba(r, g, b, 0));
      ctx.fillStyle = g1;
      ctx.beginPath();
      ctx.arc(e.x, e.y, haloR, 0, TAU);
      ctx.fill();

      // Layer 2: inner glow — strong domain color
      const innerR = bR * 2.5;
      const innerA = 0.28 * alpha * sectorBright;
      const g2 = ctx.createRadialGradient(e.x, e.y, 0, e.x, e.y, innerR);
      g2.addColorStop(0, rgba(r, g, b, innerA));
      g2.addColorStop(0.5, rgba(r, g, b, innerA * 0.4));
      g2.addColorStop(1, rgba(r, g, b, 0));
      ctx.fillStyle = g2;
      ctx.beginPath();
      ctx.arc(e.x, e.y, innerR, 0, TAU);
      ctx.fill();

      // Layer 3: color bloom — domain color radiating from center
      const bloomR = bR * 1.0;
      const bloomA = alpha * sectorBright;
      const bg = ctx.createRadialGradient(e.x, e.y, 0, e.x, e.y, bloomR);
      bg.addColorStop(0, rgba(r, g, b, 0.9 * bloomA));
      bg.addColorStop(0.3, rgba(r, g, b, 0.5 * bloomA));
      bg.addColorStop(0.7, rgba(r, g, b, 0.1 * bloomA));
      bg.addColorStop(1, rgba(r, g, b, 0));
      ctx.fillStyle = bg;
      ctx.beginPath();
      ctx.arc(e.x, e.y, bloomR, 0, TAU);
      ctx.fill();

      // Layer 4: tiny hot white core
      const coreR = bR * 0.25;
      ctx.fillStyle = `rgba(255,255,255,${min(1, 0.9 * alpha * sectorBright)})`;
      ctx.beginPath();
      ctx.arc(e.x, e.y, coreR * 0.35, 0, TAU);
      ctx.fill();
    } else {
      // Galaxy zoom — simple dot
      ctx.globalAlpha = alpha;
      ctx.fillStyle = e.color;
      ctx.beginPath();
      ctx.arc(e.x, e.y, bR, 0, TAU);
      ctx.fill();
      ctx.globalAlpha = 1;
    }

    // Activity flash ring
    if (act > 0.3) {
      ctx.strokeStyle = rgba(r, g, b, act * 0.5);
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(e.x, e.y, bR * 3, 0, TAU);
      ctx.stroke();
    }

    // Labels — only if space available (collision check via placedLabels)
    const showLabel = deepZoom || (sectorZoom && e.sourceCount >= 8);
    if (showLabel && _labelSlotFree(e.x, e.y - bR * 2 - 4, camera.zoom)) {
      const labelBright = sectorZoom ? 1.3 : 1.0;
      ctx.fillStyle = rgba(r, g, b, min(1, (0.5 + act * 0.4) * labelBright * dimFactor));
      ctx.font = "14px 'Courier New', monospace";
      ctx.textAlign = 'center';
      ctx.fillText(e.label, e.x, e.y - bR * 2 - 4);
      _labelSlotReserve(e.x, e.y - bR * 2 - 4, camera.zoom);
    }
  }

  // Clear label slots for next frame
  _labelSlotsClear();
}

// Simple grid-based label collision avoidance
const _labelGrid = new Set();
function _labelSlotFree(x, y, zoom) {
  // Quantize to grid cells — each cell is ~80px at current zoom
  const cellSize = 80 / zoom;
  const key = `${Math.round(x / cellSize)},${Math.round(y / cellSize)}`;
  return !_labelGrid.has(key);
}
function _labelSlotReserve(x, y, zoom) {
  const cellSize = 80 / zoom;
  const key = `${Math.round(x / cellSize)},${Math.round(y / cellSize)}`;
  _labelGrid.add(key);
}
function _labelSlotsClear() {
  _labelGrid.clear();
}

/** Draw trade route weight labels — only on hover via state.hoveredId */
export function drawRouteWeightLabels(ctx, state, camera) {
  // Route weight labels only show when hovering a domain —
  // shows weights on all routes connected to that domain
  if (camera.zoom < 0.4) return;
  if (!state.hoveredId) return;

  const hovDom = state.hoveredId.startsWith('dom:')
    ? state.domains.get(state.hoveredId.replace('dom:', ''))
    : null;
  if (!hovDom) return;

  for (const route of state.tradeRoutes) {
    if (route.source !== hovDom.path && route.target !== hovDom.path) continue;
    const srcDom = state.domains.get(route.source);
    const tgtDom = state.domains.get(route.target);
    if (!srcDom || !tgtDom) continue;

    const mx = (srcDom.x + tgtDom.x) / 2;
    const my = (srcDom.y + tgtDom.y) / 2;
    ctx.fillStyle = 'rgba(0,200,180,0.45)';
    ctx.font = "18px 'Courier New', monospace";
    ctx.textAlign = 'center';
    ctx.fillText(`${route.weight} shared`, mx, my - 10);
  }
}
