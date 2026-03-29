/**
 * Star View renderer — single entity with documents and co-occurring entities.
 * The deepest zoom level: a local 2-hop graph.
 */

import { sin, cos, TAU, PI, hexRGB, rgba, clamp, min, max, sqrt } from '../core/utils.js';

const TYPE_COLORS = {
  Person: '#378ADD', Organization: '#7F77DD', Product: '#1D9E75',
  Technology: '#BA7517', Event: '#D85A30', Concept: '#9c9a92',
  Location: '#5DCAA5', Process: '#6BBACC', Tool: '#BA7517',
};

function typeColor(type) { return TYPE_COLORS[type] || '#9c9a92'; }

/** Draw the central entity star */
export function drawCentralStar(ctx, entity, tick) {
  const tc = typeColor(entity.type);
  const [r, g, b] = hexRGB(tc);
  const act = entity.activityGlow || 0;
  const boost = 1 + act * 2.0;
  const breathe = 0.95 + 0.05 * sin(tick * 0.0015);
  const sz = entity.radius;

  // Wide halo
  const g1 = ctx.createRadialGradient(entity.x, entity.y, 0, entity.x, entity.y, sz * 5);
  g1.addColorStop(0, rgba(r, g, b, 0.08 * boost));
  g1.addColorStop(0.3, rgba(r, g, b, 0.03 * boost));
  g1.addColorStop(1, rgba(r, g, b, 0));
  ctx.fillStyle = g1;
  ctx.beginPath();
  ctx.arc(entity.x, entity.y, sz * 5, 0, TAU);
  ctx.fill();

  // Inner glow
  const g2 = ctx.createRadialGradient(entity.x, entity.y, 0, entity.x, entity.y, sz * 1.8);
  g2.addColorStop(0, rgba(r, g, b, 0.25 * boost));
  g2.addColorStop(0.5, rgba(r, g, b, 0.10 * boost));
  g2.addColorStop(1, rgba(r, g, b, 0));
  ctx.fillStyle = g2;
  ctx.beginPath();
  ctx.arc(entity.x, entity.y, sz * 1.8, 0, TAU);
  ctx.fill();

  // Core star
  ctx.shadowBlur = sz * 2;
  ctx.shadowColor = `rgba(255,255,255,${0.4 * boost})`;
  const g3 = ctx.createRadialGradient(entity.x, entity.y, 0, entity.x, entity.y, sz * 0.6);
  g3.addColorStop(0, `rgba(255,255,255,${min(1, 0.95 * boost * breathe)})`);
  g3.addColorStop(0.4, rgba(r, g, b, 0.8 * boost));
  g3.addColorStop(1, rgba(r, g, b, 0));
  ctx.fillStyle = g3;
  ctx.beginPath();
  ctx.arc(entity.x, entity.y, sz * 0.6, 0, TAU);
  ctx.fill();
  ctx.shadowBlur = 0;

  // Spikes
  const spikeLen = sz * 2.5 * breathe;
  const spikeA = 0.25 * boost;
  for (let s = 0; s < 4; s++) {
    const a = s * PI / 2 + tick * 0.0002;
    const x2 = entity.x + cos(a) * spikeLen;
    const y2 = entity.y + sin(a) * spikeLen;
    const spg = ctx.createLinearGradient(entity.x, entity.y, x2, y2);
    spg.addColorStop(0, `rgba(255,255,255,${spikeA})`);
    spg.addColorStop(0.3, rgba(r, g, b, spikeA * 0.5));
    spg.addColorStop(1, rgba(r, g, b, 0));
    ctx.strokeStyle = spg;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(entity.x, entity.y);
    ctx.lineTo(x2, y2);
    ctx.stroke();
  }

  // Label
  ctx.fillStyle = `rgba(220,215,200,${0.65 * boost})`;
  ctx.font = `400 22px 'Courier New', monospace`;
  ctx.textAlign = 'center';
  ctx.fillText(entity.name, entity.x, entity.y + sz * 3.5);
  ctx.font = "14px 'Courier New', monospace";
  const [tr, tg, tb] = hexRGB(tc);
  ctx.fillStyle = rgba(tr, tg, tb, 0.45);
  ctx.fillText(`${entity.type} · ${entity.sourceCount} docs`, entity.x, entity.y + sz * 3.5 + 20);
}

/** Draw document nodes orbiting the entity */
export function drawDocuments(ctx, docs, tick, hoveredId) {
  for (const doc of docs) {
    const hov = hoveredId === doc.id;
    const act = doc.activityGlow || 0;
    const alpha = clamp(0.6 + act * 0.4, 0, 1) * (hov ? 1.3 : 1);

    // Orbital drift
    const ox = sin(tick * 0.0002 * doc.orbitSpeed + doc.orbitPhase) * doc.orbitDrift;
    const oy = cos(tick * 0.00025 * doc.orbitSpeed + doc.orbitPhase * 1.2) * doc.orbitDrift * 0.7;
    const px = doc.x + ox;
    const py = doc.y + oy;
    doc._px = px;
    doc._py = py;

    // Document node — warm amber square-ish glow
    const sz = doc.radius;
    const g1 = ctx.createRadialGradient(px, py, 0, px, py, sz * 2.5);
    g1.addColorStop(0, `rgba(255,200,120,${0.20 * alpha})`);
    g1.addColorStop(0.5, `rgba(200,150,80,${0.08 * alpha})`);
    g1.addColorStop(1, 'rgba(180,120,60,0)');
    ctx.fillStyle = g1;
    ctx.beginPath();
    ctx.arc(px, py, sz * 2.5, 0, TAU);
    ctx.fill();

    // Core
    ctx.fillStyle = `rgba(255,220,160,${0.8 * alpha})`;
    ctx.beginPath();
    ctx.arc(px, py, sz * 0.5, 0, TAU);
    ctx.fill();

    // Tiny document icon — two horizontal lines
    ctx.strokeStyle = `rgba(255,220,160,${0.5 * alpha})`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(px - sz * 0.3, py - sz * 0.15);
    ctx.lineTo(px + sz * 0.3, py - sz * 0.15);
    ctx.moveTo(px - sz * 0.3, py + sz * 0.15);
    ctx.lineTo(px + sz * 0.2, py + sz * 0.15);
    ctx.stroke();

    // Label — always show (truncated)
    const label = doc.title.length > 30 ? doc.title.slice(0, 28) + '…' : doc.title;
    ctx.fillStyle = `rgba(255,230,180,${(hov ? 0.9 : 0.45) * alpha})`;
    ctx.font = `${hov ? 16 : 13}px 'Courier New', monospace`;
    ctx.textAlign = 'center';
    ctx.fillText(label, px, py + sz * 2 + 10);
  }
}

/** Draw co-occurring entities */
export function drawCoEntities(ctx, coEntities, tick, hoveredId) {
  for (const e of coEntities) {
    const hov = hoveredId === e.id;
    const tc = typeColor(e.type);
    const [rc, gc, bc] = hexRGB(tc);
    const act = e.activityGlow || 0;
    const alpha = clamp(0.4 + act * 0.5, 0, 1) * (hov ? 1.3 : 1);

    // Slow drift
    const ox = sin(tick * 0.00015 * e.orbitSpeed + e.orbitPhase) * e.orbitDrift;
    const oy = cos(tick * 0.0002 * e.orbitSpeed + e.orbitPhase * 1.4) * e.orbitDrift * 0.6;
    const px = e.x + ox;
    const py = e.y + oy;
    e._px = px;
    e._py = py;

    // Glow
    const glowR = e.radius * 3;
    const gg = ctx.createRadialGradient(px, py, 0, px, py, glowR);
    gg.addColorStop(0, rgba(rc, gc, bc, 0.2 * alpha));
    gg.addColorStop(0.5, rgba(rc, gc, bc, 0.06 * alpha));
    gg.addColorStop(1, rgba(rc, gc, bc, 0));
    ctx.fillStyle = gg;
    ctx.beginPath();
    ctx.arc(px, py, glowR, 0, TAU);
    ctx.fill();

    // Core
    const cg = ctx.createRadialGradient(px, py, 0, px, py, e.radius * 0.5);
    cg.addColorStop(0, `rgba(255,255,255,${0.8 * alpha})`);
    cg.addColorStop(0.5, rgba(rc, gc, bc, 0.7 * alpha));
    cg.addColorStop(1, rgba(rc, gc, bc, 0));
    ctx.fillStyle = cg;
    ctx.beginPath();
    ctx.arc(px, py, e.radius * 0.5, 0, TAU);
    ctx.fill();

    // Label
    const showLabel = hov || e.weight >= e.labelThreshold;
    if (showLabel) {
      ctx.fillStyle = `rgba(255,240,220,${hov ? 0.9 : 0.45})`;
      ctx.font = `${hov ? 16 : 12}px 'Courier New', monospace`;
      ctx.textAlign = 'center';
      ctx.fillText(e.name, px, py - e.radius * 2 - 4);
      if (hov) {
        ctx.font = "11px 'Courier New', monospace";
        ctx.fillStyle = rgba(rc, gc, bc, 0.5);
        ctx.fillText(`${e.type} · ${e.weight} shared`, px, py - e.radius * 2 + 10);
      }
    }
  }
}

/** Draw the full 2-hop connection graph.
 *  center ↔ docs (always),  doc ↔ co-entity (via shared_doc_ids),
 *  Hover highlights the full chain: hover doc → light up its co-entities,
 *  hover co-entity → light up its shared docs.
 */
export function drawConnections(ctx, centerX, centerY, docs, coEntities, hoveredId) {
  const hovDoc = docs.find(d => d.id === hoveredId);
  const hovCo = coEntities.find(e => e.id === hoveredId);

  // Center → documents
  for (const doc of docs) {
    const lit = hovDoc && doc.id === hovDoc.id;
    ctx.strokeStyle = `rgba(255,200,120,${lit ? 0.30 : 0.04})`;
    ctx.lineWidth = lit ? 1.8 : 0.5;
    ctx.setLineDash([3, 8]);
    ctx.beginPath();
    ctx.moveTo(centerX, centerY);
    ctx.lineTo(doc._px, doc._py);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // Doc ↔ co-entity links
  for (const co of coEntities) {
    if (!co.sharedDocIds) continue;
    const coHov = hovCo && co.id === hovCo.id;
    for (const docId of co.sharedDocIds) {
      const doc = docs.find(d => d.id === docId);
      if (!doc) continue;
      // Light up if: hovering this co-entity, or hovering this doc
      const lit = coHov || (hovDoc && doc.id === hovDoc.id);
      const tc = typeColor(co.type);
      const [rc, gc, bc] = hexRGB(tc);
      ctx.strokeStyle = rgba(rc, gc, bc, lit ? 0.25 : 0.035);
      ctx.lineWidth = lit ? 1.2 : 0.4;
      ctx.setLineDash([2, 6]);
      ctx.beginPath();
      ctx.moveTo(doc._px, doc._py);
      ctx.lineTo(co._px, co._py);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }
}
