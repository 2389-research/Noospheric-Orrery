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
export function drawDomainNebula(ctx, dom, tick) {
  const [r, g, b] = hexRGB(dom.color);
  const bR = dom.radius * clamp(dom.birthScale, 0, 1);
  const brightness = 1 + dom.activityGlow * 1.8;

  if (dom.simmering) {
    _drawSimmering(ctx, dom, bR, r, g, b, tick, brightness);
  } else if (dom.maturity > 0) {
    _drawFormed(ctx, dom, bR, r, g, b, tick, brightness);
  } else {
    _drawUnformed(ctx, dom, bR, r, g, b, tick, brightness);
  }

  // Label
  const labelY = dom.y + bR * 1.8 + 20;
  ctx.fillStyle = rgba(r, g, b, 0.9 * brightness);
  ctx.font = `${dom.isSubdomain ? 28 : 36}px 'Courier New', monospace`;
  ctx.textAlign = 'center';
  ctx.fillText(dom.label.split('/').pop(), dom.x, labelY);
  ctx.fillStyle = rgba(r, g, b, 0.4);
  ctx.font = "24px 'Courier New', monospace";
  ctx.fillText(`${dom.docCount} docs`, dom.x, labelY + 30);
}

function _drawUnformed(ctx, dom, bR, r, g, b, tick, brightness) {
  for (let i = 0; i < 4; i++) {
    const angle = dom.rot * (1 - i * 0.15) + i * 1.4;
    const lr = bR * (2.0 - i * 0.15);
    const ox = cos(angle) * bR * 0.12, oy = sin(angle) * bR * 0.08;
    const a = (0.04 - i * 0.007) * clamp(dom.birthScale, 0, 1) * brightness;
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
    const baseA = (0.05 + maturity * 0.025 - i * 0.006) * clamp(dom.birthScale, 0, 1) * brightness;
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

/** Draw faint trade routes between clusters */
export function drawTradeRoutes(ctx, state) {
  for (const route of state.tradeRoutes) {
    const srcDom = state.domains.get(route.source);
    const tgtDom = state.domains.get(route.target);
    if (!srcDom || !tgtDom) continue;

    const a = 0.04 + Math.min(route.weight / 10000, 0.1);
    ctx.setLineDash([8, 16]);
    ctx.strokeStyle = rgba(0, 200, 180, a);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(srcDom.x, srcDom.y);
    ctx.lineTo(tgtDom.x, tgtDom.y);
    ctx.stroke();
    ctx.setLineDash([]);
  }
}

/** Draw entity stars (small dots at galaxy zoom) */
export function drawEntityStars(ctx, state, camera) {
  if (camera.zoom < 0.35) return; // entities only visible at sector zoom and below

  for (const [, e] of state.entities) {
    if (e.birthScale < 0.1) continue;
    const bR = (e.radius * 0.6 + e.activityGlow * 3) * e.birthScale;
    const [r, g, b] = hexRGB(e.color);
    const alpha = clamp(0.3 + e.activityGlow * 0.7, 0, 1);

    ctx.globalAlpha = alpha;
    ctx.fillStyle = e.color;
    ctx.beginPath();
    ctx.arc(e.x, e.y, bR, 0, TAU);
    ctx.fill();
    ctx.globalAlpha = 1;
  }
}
