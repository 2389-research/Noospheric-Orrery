/**
 * Sector View renderer — focused domain nebulae + trade routes + key entities.
 * Shows a single cluster in detail with edge domains from neighbors.
 */

import { sin, cos, TAU, PI, hexRGB, rgba, clamp, min, max, sqrt } from '../core/utils.js';

/** Draw dim edge domains at periphery */
export function drawEdgeDomains(ctx, edgeDomains) {
  for (const d of edgeDomains) {
    const { x, y, radius: r, color } = d;
    const [rc, gc, bc] = hexRGB(color);

    const g = ctx.createRadialGradient(x, y, 0, x, y, r * 2);
    g.addColorStop(0, rgba(rc, gc, bc, 0.018));
    g.addColorStop(1, rgba(rc, gc, bc, 0));
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(x, y, r * 2, 0, TAU);
    ctx.fill();

    // Faint label
    ctx.fillStyle = rgba(rc, gc, bc, 0.18);
    ctx.font = "20px 'Courier New', monospace";
    ctx.textAlign = 'center';
    ctx.fillText(d.label, x, y + r * 1.8 + 20);
  }
}

/** Draw trade routes with weight labels */
export function drawSectorRoutes(ctx, routes, domains, hoveredRouteIdx, pulses) {
  const maxWeight = Math.max(1, ...routes.map(r => r.weight));

  // Draw route lines
  for (let i = 0; i < routes.length; i++) {
    const route = routes[i];
    const srcDom = domains.get(route.source);
    const tgtDom = domains.get(route.target);
    if (!srcDom || !tgtDom) continue;

    const wt = route.weight / maxWeight;
    const hov = hoveredRouteIdx === i;
    const alpha = hov ? 0.5 : 0.08 + wt * 0.15;
    const lw = hov ? 2.5 : 0.8 + wt * 2.0;

    ctx.strokeStyle = rgba(200, 130, 80, alpha);
    ctx.lineWidth = lw;
    ctx.setLineDash([4, 10]);
    ctx.beginPath();
    ctx.moveTo(srcDom.x, srcDom.y);
    ctx.lineTo(tgtDom.x, tgtDom.y);
    ctx.stroke();
    ctx.setLineDash([]);

    // Weight label on routes with weight >= 20 or hovered
    if (route.weight >= 20 || hov) {
      const mx = (srcDom.x + tgtDom.x) / 2;
      const my = (srcDom.y + tgtDom.y) / 2;
      ctx.fillStyle = rgba(200, 140, 80, hov ? 0.7 : 0.3);
      ctx.font = "22px 'Courier New', monospace";
      ctx.textAlign = 'center';
      ctx.fillText(`${route.weight} shared`, mx, my - 12);
    }
  }

  // Draw traveling pulses
  for (const p of pulses) {
    const srcDom = domains.get(p.source);
    const tgtDom = domains.get(p.target);
    if (!srcDom || !tgtDom) continue;

    const rawP = p.progress;
    const ep = rawP < 0.5 ? 2 * rawP * rawP : -1 + (4 - 2 * rawP) * rawP;
    const gf = sin(rawP * Math.PI);

    const ax = srcDom.x, ay = srcDom.y;
    const bx = tgtDom.x, by = tgtDom.y;
    const px = ax + (bx - ax) * ep;
    const py = ay + (by - ay) * ep;

    // Trail — warm amber
    const trailP = max(0, rawP - 0.12);
    const tep = trailP < 0.5 ? 2 * trailP * trailP : -1 + (4 - 2 * trailP) * trailP;
    const tx = ax + (bx - ax) * tep;
    const ty = ay + (by - ay) * tep;
    const tg = ctx.createLinearGradient(tx, ty, px, py);
    tg.addColorStop(0, `rgba(255,200,140,0)`);
    tg.addColorStop(1, `rgba(255,200,140,${0.55 * gf})`);
    ctx.strokeStyle = tg;
    ctx.lineWidth = 3.5;
    ctx.beginPath();
    ctx.moveTo(tx, ty);
    ctx.lineTo(px, py);
    ctx.stroke();

    // Dot — white core → domain color
    const [pr, pg, pb] = p.col;
    const sz = 18 + gf * 10;
    const dg = ctx.createRadialGradient(px, py, 0, px, py, sz);
    dg.addColorStop(0, `rgba(255,255,255,${0.98 * gf})`);
    dg.addColorStop(0.2, `rgba(${pr},${pg},${pb},${0.85 * gf})`);
    dg.addColorStop(0.7, `rgba(${pr},${pg},${pb},${0.2 * gf})`);
    dg.addColorStop(1, `rgba(${pr},${pg},${pb},0)`);
    ctx.fillStyle = dg;
    ctx.beginPath();
    ctx.arc(px, py, sz, 0, TAU);
    ctx.fill();

    // Arrival ripple
    if (rawP > 0.82) {
      const rp = (rawP - 0.82) / 0.18;
      const rippleR = tgtDom.radius * (0.18 + rp * 0.75);
      ctx.strokeStyle = `rgba(255,200,140,${(1 - rp) * 0.6})`;
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      ctx.arc(tgtDom.x, tgtDom.y, rippleR, 0, TAU);
      ctx.stroke();
    }
  }
}

/** Draw sector domain nebula — larger, richer labels */
export function drawSectorDomain(ctx, dom, tick, hoveredId) {
  const [r, g, b] = hexRGB(dom.color);
  const bR = dom.radius * clamp(dom.birthScale, 0, 1);
  const act = dom.activityGlow;
  const boost = 1 + act * 2.5;
  const hov = hoveredId === dom.id;

  // Outer halo
  const g1 = ctx.createRadialGradient(dom.x, dom.y, 0, dom.x, dom.y, bR * 2.8);
  g1.addColorStop(0, rgba(r, g, b, 0.03 * boost * (hov ? 1.4 : 1)));
  g1.addColorStop(0.5, rgba(r, g, b, 0.012 * boost));
  g1.addColorStop(1, rgba(r, g, b, 0));
  ctx.fillStyle = g1;
  ctx.beginPath();
  ctx.arc(dom.x, dom.y, bR * 2.8, 0, TAU);
  ctx.fill();

  // Inner body
  const g2 = ctx.createRadialGradient(dom.x, dom.y, 0, dom.x, dom.y, bR * 1.2);
  g2.addColorStop(0, rgba(r, g, b, 0.13 * boost));
  g2.addColorStop(0.6, rgba(r, g, b, 0.05 * boost));
  g2.addColorStop(1, rgba(r, g, b, 0));
  ctx.fillStyle = g2;
  ctx.beginPath();
  ctx.arc(dom.x, dom.y, bR * 1.2, 0, TAU);
  ctx.fill();

  // Formed star (has spec)
  if (dom.maturity > 0) {
    const cb = 0.6 + act * 0.4;

    // Inner glow
    const g3 = ctx.createRadialGradient(dom.x, dom.y, 0, dom.x, dom.y, bR * 0.22);
    g3.addColorStop(0, rgba(r, g, b, 0.5 * cb));
    g3.addColorStop(1, rgba(r, g, b, 0));
    ctx.fillStyle = g3;
    ctx.beginPath();
    ctx.arc(dom.x, dom.y, bR * 0.22, 0, TAU);
    ctx.fill();

    // Core star point
    const g4 = ctx.createRadialGradient(dom.x, dom.y, 0, dom.x, dom.y, bR * 0.045);
    g4.addColorStop(0, `rgba(255,255,255,${cb})`);
    g4.addColorStop(0.5, rgba(r, g, b, cb * 0.7));
    g4.addColorStop(1, rgba(r, g, b, 0));
    ctx.fillStyle = g4;
    ctx.beginPath();
    ctx.arc(dom.x, dom.y, bR * 0.045, 0, TAU);
    ctx.fill();

    // Spikes
    const sl = bR * 0.55 * cb;
    for (let s = 0; s < 4; s++) {
      const a = s * PI / 2;
      const x2 = dom.x + cos(a) * sl, y2 = dom.y + sin(a) * sl;
      const sg = ctx.createLinearGradient(dom.x, dom.y, x2, y2);
      sg.addColorStop(0, `rgba(255,255,255,${0.25 * cb})`);
      sg.addColorStop(1, rgba(r, g, b, 0));
      ctx.strokeStyle = sg;
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.moveTo(dom.x, dom.y);
      ctx.lineTo(x2, y2);
      ctx.stroke();
    }
  }

  // Simmering cocoon
  if (dom.simmering) {
    const pulse = 0.7 + 0.3 * sin(tick * 0.003);
    const cocoon = ctx.createRadialGradient(dom.x, dom.y, 0, dom.x, dom.y, bR * 0.55);
    cocoon.addColorStop(0, `rgba(255,160,60,${0.10 * pulse * boost})`);
    cocoon.addColorStop(0.5, `rgba(220,100,30,${0.05 * pulse * boost})`);
    cocoon.addColorStop(1, 'rgba(180,60,10,0)');
    ctx.fillStyle = cocoon;
    ctx.beginPath();
    ctx.arc(dom.x, dom.y, bR * 0.55, 0, TAU);
    ctx.fill();
  }

  // Activity ring
  if (act > 0.2) {
    const ringR = bR * (1.0 + act * 0.7);
    ctx.strokeStyle = rgba(r, g, b, act * 0.5);
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(dom.x, dom.y, ringR, 0, TAU);
    ctx.stroke();
  }

  // Hover ring
  if (hov) {
    ctx.strokeStyle = rgba(r, g, b, 0.35);
    ctx.lineWidth = 1.5;
    ctx.setLineDash([6, 10]);
    ctx.beginPath();
    ctx.arc(dom.x, dom.y, bR * 1.5, 0, TAU);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // Label block — richer metadata
  const la = 0.35 + act * 0.5 + (hov ? 0.2 : 0);
  const labelY = dom.y + bR * 1.5 + 30;
  ctx.fillStyle = rgba(r, g, b, la);
  ctx.font = `600 28px 'Courier New', monospace`;
  ctx.textAlign = 'center';
  ctx.fillText(dom.label.split('/').pop(), dom.x, labelY);

  ctx.font = "22px 'Courier New', monospace";
  ctx.fillStyle = rgba(r, g, b, la * 0.6);
  const specStr = dom.maturity > 0 ? `spec v${dom.specVersion || '?'}` : 'no spec';
  const meta = `${specStr} · ${dom.docCount} docs · ${dom.entityCount || '?'} entities`;
  ctx.fillText(meta, dom.x, labelY + 28);
}

/** Draw key entities as small stars */
export function drawSectorEntities(ctx, entities, hoveredEntityId) {
  for (const e of entities) {
    const hov = hoveredEntityId === e.id;
    const [rc, gc, bc] = hexRGB(e.color);
    const alpha = e.bright * (hov ? 1.3 : 1);

    // Glow
    const glowR = e.radius * 4;
    const g = ctx.createRadialGradient(e.x, e.y, 0, e.x, e.y, glowR);
    g.addColorStop(0, rgba(rc, gc, bc, 0.3 * alpha));
    g.addColorStop(1, rgba(rc, gc, bc, 0));
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(e.x, e.y, glowR, 0, TAU);
    ctx.fill();

    // Core dot
    ctx.fillStyle = `rgba(255,255,255,${alpha * 0.9})`;
    ctx.beginPath();
    ctx.arc(e.x, e.y, e.radius * 0.6, 0, TAU);
    ctx.fill();

    // Bridge marker ring
    if (e.bridge) {
      ctx.strokeStyle = `rgba(255,255,255,${alpha * 0.35})`;
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.arc(e.x, e.y, e.radius * 1.6, 0, TAU);
      ctx.stroke();
    }

    // Label on hover
    if (hov) {
      ctx.fillStyle = 'rgba(255,240,220,0.9)';
      ctx.font = "22px 'Courier New', monospace";
      ctx.textAlign = 'center';
      ctx.fillText(e.name, e.x, e.y - e.radius * 2.5);
    }
  }
}
