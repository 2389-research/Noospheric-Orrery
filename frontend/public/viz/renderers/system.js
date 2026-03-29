/**
 * System View renderer — single domain with orbiting entity stars.
 * Shows entity population, importance, and orbital motion.
 */

import { sin, cos, TAU, PI, hexRGB, rgba, clamp, min, max, sqrt } from '../core/utils.js';

/** Type → color mapping for entities */
const TYPE_COLORS = {
  Person: '#378ADD',
  Organization: '#7F77DD',
  Product: '#1D9E75',
  Technology: '#BA7517',
  Event: '#D85A30',
  Concept: '#9c9a92',
  Location: '#5DCAA5',
  Process: '#6BBACC',
  Tool: '#BA7517',
};

function typeColor(type) {
  return TYPE_COLORS[type] || '#9c9a92';
}

/** Draw the domain core nebula — large, fills viewport */
export function drawSystemCore(ctx, dom, tick) {
  const [r, g, b] = hexRGB(dom.color);
  const bR = dom.radius;
  const act = dom.activityGlow;
  const boost = 1 + act * 2.5;
  const breathe = 0.96 + 0.04 * sin(tick * 0.001);

  // Outer halo — very large
  const g1 = ctx.createRadialGradient(dom.x, dom.y, 0, dom.x, dom.y, bR * 3.5);
  g1.addColorStop(0, rgba(r, g, b, 0.04 * boost));
  g1.addColorStop(0.3, rgba(r, g, b, 0.02 * boost));
  g1.addColorStop(0.7, rgba(r, g, b, 0.008 * boost));
  g1.addColorStop(1, rgba(r, g, b, 0));
  ctx.fillStyle = g1;
  ctx.beginPath();
  ctx.arc(dom.x, dom.y, bR * 3.5, 0, TAU);
  ctx.fill();

  // Cloud layers (slow rotation)
  for (let i = 0; i < 5; i++) {
    const angle = (dom.rot || 0) * (1 - i * 0.12) + i * 1.2;
    const lr = bR * (2.2 - i * 0.15);
    const ox = cos(angle) * bR * 0.08;
    const oy = sin(angle) * bR * 0.06;
    const a = (0.055 + dom.maturity * 0.025 - i * 0.006) * boost;
    const gr = ctx.createRadialGradient(
      dom.x + ox, dom.y + oy, dom.maturity > 0 ? bR * 0.15 : 0,
      dom.x + ox, dom.y + oy, lr
    );
    if (dom.maturity > 0) {
      gr.addColorStop(0, rgba(r, g, b, 0));
      gr.addColorStop(0.1, rgba(r, g, b, a * 1.6));
    } else {
      gr.addColorStop(0, rgba(r, g, b, a * 2));
    }
    gr.addColorStop(0.5, rgba(r, g, b, a));
    gr.addColorStop(1, rgba(r, g, b, 0));
    ctx.fillStyle = gr;
    ctx.beginPath();
    ctx.arc(dom.x + ox, dom.y + oy, lr, 0, TAU);
    ctx.fill();
  }

  // Inner glow
  if (dom.maturity > 0) {
    const wh = ctx.createRadialGradient(dom.x, dom.y, 0, dom.x, dom.y, bR * 0.6);
    wh.addColorStop(0, rgba(r, g, b, 0.18 * boost * breathe));
    wh.addColorStop(0.4, rgba(r, g, b, 0.06 * boost));
    wh.addColorStop(1, rgba(r, g, b, 0));
    ctx.fillStyle = wh;
    ctx.beginPath();
    ctx.arc(dom.x, dom.y, bR * 0.6, 0, TAU);
    ctx.fill();
  }

  // Star point (formed domains)
  if (dom.maturity > 0) {
    const cb = (0.5 + dom.maturity * 0.5) * boost * breathe;
    const coreR = bR * (0.08 + dom.maturity * 0.05);

    ctx.shadowBlur = coreR * 3;
    ctx.shadowColor = `rgba(255,255,255,${0.3 * cb})`;
    const sg = ctx.createRadialGradient(dom.x, dom.y, 0, dom.x, dom.y, coreR);
    sg.addColorStop(0, `rgba(255,255,255,${min(1.0, cb)})`);
    sg.addColorStop(0.4, rgba(r, g, b, 0.8 * cb));
    sg.addColorStop(1, rgba(r, g, b, 0));
    ctx.fillStyle = sg;
    ctx.beginPath();
    ctx.arc(dom.x, dom.y, coreR, 0, TAU);
    ctx.fill();
    ctx.shadowBlur = 0;

    // Spikes
    const spikeLen = bR * (0.4 + dom.maturity * 1.2);
    const spikeA = cb * 0.3;
    for (let s = 0; s < 4; s++) {
      const a = s * PI / 2;
      const x2 = dom.x + cos(a) * spikeLen;
      const y2 = dom.y + sin(a) * spikeLen;
      const spg = ctx.createLinearGradient(dom.x, dom.y, x2, y2);
      spg.addColorStop(0, `rgba(255,255,255,${spikeA})`);
      spg.addColorStop(0.3, rgba(r, g, b, spikeA * 0.5));
      spg.addColorStop(1, rgba(r, g, b, 0));
      ctx.strokeStyle = spg;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(dom.x, dom.y);
      ctx.lineTo(x2, y2);
      ctx.stroke();
    }
  }

  // Simmering cocoon
  if (dom.simmering) {
    const pulse = 0.7 + 0.3 * sin(tick * 0.003);
    const cocoon = ctx.createRadialGradient(dom.x, dom.y, 0, dom.x, dom.y, bR * 0.5);
    cocoon.addColorStop(0, `rgba(255,160,60,${0.12 * pulse * boost})`);
    cocoon.addColorStop(0.5, `rgba(220,100,30,${0.06 * pulse * boost})`);
    cocoon.addColorStop(1, 'rgba(180,60,10,0)');
    ctx.fillStyle = cocoon;
    ctx.beginPath();
    ctx.arc(dom.x, dom.y, bR * 0.5, 0, TAU);
    ctx.fill();
  }

  // Activity ring
  if (act > 0.15) {
    const ringR = bR * (1.2 + act * 0.8);
    ctx.strokeStyle = rgba(r, g, b, act * 0.4);
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    ctx.arc(dom.x, dom.y, ringR, 0, TAU);
    ctx.stroke();
  }

  // Domain label
  const labelY = dom.y + bR * 2.5 + 30;
  ctx.fillStyle = rgba(r, g, b, 0.7 + act * 0.3);
  ctx.font = `600 32px 'Courier New', monospace`;
  ctx.textAlign = 'center';
  ctx.fillText(dom.label.split('/').pop(), dom.x, labelY);

  ctx.font = "22px 'Courier New', monospace";
  ctx.fillStyle = rgba(r, g, b, 0.4);
  const specStr = dom.maturity > 0 ? `spec v${dom.specVersion || '?'}` : 'no spec';
  ctx.fillText(`${specStr} · ${dom.docCount} docs`, dom.x, labelY + 28);
}

/** Draw orbiting entity stars */
export function drawSystemEntities(ctx, entities, tick, hoveredId, labelThreshold) {
  for (const e of entities) {
    const hov = hoveredId === e.id;
    const tc = typeColor(e.type);
    const [rc, gc, bc] = hexRGB(tc);
    const act = e.activityGlow || 0;
    const alpha = clamp(0.5 + act * 0.5, 0, 1) * (hov ? 1.3 : 1);

    // Orbital drift
    const ox = sin(tick * 0.0003 * e.orbitSpeed + e.orbitPhase) * e.orbitDrift;
    const oy = cos(tick * 0.0004 * e.orbitSpeed + e.orbitPhase * 1.3) * e.orbitDrift * 0.7;
    const px = e.x + ox;
    const py = e.y + oy;

    // Glow
    const glowR = e.radius * (3 + act * 2);
    const gg = ctx.createRadialGradient(px, py, 0, px, py, glowR);
    gg.addColorStop(0, rgba(rc, gc, bc, 0.25 * alpha));
    gg.addColorStop(0.5, rgba(rc, gc, bc, 0.08 * alpha));
    gg.addColorStop(1, rgba(rc, gc, bc, 0));
    ctx.fillStyle = gg;
    ctx.beginPath();
    ctx.arc(px, py, glowR, 0, TAU);
    ctx.fill();

    // Core star
    const coreR = e.radius * 0.5;
    const cg = ctx.createRadialGradient(px, py, 0, px, py, coreR);
    cg.addColorStop(0, `rgba(255,255,255,${0.95 * alpha})`);
    cg.addColorStop(0.4, rgba(rc, gc, bc, 0.8 * alpha));
    cg.addColorStop(1, rgba(rc, gc, bc, 0));
    ctx.fillStyle = cg;
    ctx.beginPath();
    ctx.arc(px, py, coreR, 0, TAU);
    ctx.fill();

    // Bridge entity halo
    if (e.bridge) {
      ctx.strokeStyle = rgba(rc, gc, bc, 0.3 * alpha);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(px, py, e.radius * 1.8, 0, TAU);
      ctx.stroke();
    }

    // Activity flash ring
    if (act > 0.3) {
      ctx.strokeStyle = rgba(rc, gc, bc, act * 0.5);
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(px, py, e.radius * (1.5 + act * 1.0), 0, TAU);
      ctx.stroke();
    }

    // Label — always for top entities, hover for rest
    const showLabel = hov || e.sourceCount >= labelThreshold;
    if (showLabel) {
      const la = hov ? 0.9 : 0.5 + act * 0.3;
      ctx.fillStyle = `rgba(255,240,220,${la})`;
      ctx.font = `${hov ? 22 : 18}px 'Courier New', monospace`;
      ctx.textAlign = 'center';
      ctx.fillText(e.name, px, py - e.radius * 2 - 6);

      if (hov) {
        ctx.font = "14px 'Courier New', monospace";
        ctx.fillStyle = rgba(rc, gc, bc, 0.6);
        ctx.fillText(`${e.type} · ${e.sourceCount} docs`, px, py - e.radius * 2 + 12);
      }
    }

    // Store current rendered position for hit testing
    e._px = px;
    e._py = py;
  }
}
