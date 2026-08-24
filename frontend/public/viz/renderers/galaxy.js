/**
 * Galaxy View renderer — cluster clouds + domain nebulae + faint routes.
 * Renders at zoom < 0.35
 */

import { sin, cos, TAU, PI, hexRGB, rgba, colorAlpha, clamp, min, max } from '../core/utils.js';
import { entityGlowSprite, ENTITY_BR0, repoCoreSprite, REPO_CORE0, SECTOR_BRIGHT, domainNebulaSprite, DOM_BR0, NEB_BAKE } from './sprites.js';

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
  // Three-tier emphasis when a node is hovered/selected: the ACTIVE domain stays
  // full, its CONNECTED neighbors sit at a reduced level (present but clearly
  // secondary to the one you're on), and everything unrelated dims the most.
  // (Previously neighbors matched the active domain at full brightness.)
  const hasNb = neighborhood && neighborhood.size > 0;
  const isActiveDom = dom.id === dom._hoveredId || dom.id === dom._pinnedId;
  const inNb = hasNb && neighborhood.has(dom.id);
  const dimFactor = !hasNb ? 1.0 : isActiveDom ? 1.0 : inNb ? 0.55 : 0.3;
  const brightness = (1 + act * 2.2 + zoomBright) * dimFactor;

  // The expensive cloud/halo/shadowBlur-star/spike stack is pre-baked per
  // (color, state, maturity) into an offscreen sprite (see sprites.js) and
  // drawImage'd here — scaled by radius, brightness applied via globalAlpha —
  // instead of rebuilt every frame. This flattens the per-frame gradient/blur
  // cost that used to peak (and drop FPS) in the mid-zoom band.
  const state = dom.simmering ? 'simmering' : (dom.maturity > 0 ? 'formed' : 'unformed');
  if (bR > 0) {
    const sprite = domainNebulaSprite(dom.color, state, dom.maturity);
    const half = (sprite.width * 0.5) * (bR / DOM_BR0);
    const prevAlpha = ctx.globalAlpha;
    // Sprite is baked at reference brightness NEB_BAKE; below that we scale down via
    // globalAlpha. When brightness exceeds NEB_BAKE (activity pulse / zoom-in flare),
    // a second additive drawImage pass re-brightens past the baked level so pulses
    // still visibly flare instead of clamping flat.
    const norm = brightness / NEB_BAKE;
    ctx.globalAlpha = clamp(norm, 0, 1);
    ctx.drawImage(sprite, dom.x - half, dom.y - half, half * 2, half * 2);
    if (norm > 1) {
      ctx.globalAlpha = clamp(norm - 1, 0, 1);
      ctx.drawImage(sprite, dom.x - half, dom.y - half, half * 2, half * 2);
    }
    ctx.globalAlpha = prevAlpha;
  }

  // Simmering domains keep their animated amber cocoon + flickering core direct
  // (only the static cloud layers are baked; there are just a handful of these).
  if (dom.simmering && bR > 0) {
    const pulse = 0.7 + 0.3 * sin(tick * 0.003);
    const cocoon = ctx.createRadialGradient(dom.x, dom.y, 0, dom.x, dom.y, bR * 0.55);
    cocoon.addColorStop(0, `rgba(255,160,60,${0.10 * pulse * brightness})`);
    cocoon.addColorStop(0.5, `rgba(220,100,30,${0.05 * pulse * brightness})`);
    cocoon.addColorStop(1, 'rgba(180,60,10,0)');
    ctx.fillStyle = cocoon;
    ctx.beginPath(); ctx.arc(dom.x, dom.y, bR * 0.55, 0, TAU); ctx.fill();

    const flicker = 0.5 + 0.5 * sin(tick * 0.007 + sin(tick * 0.013));
    const coreR = bR * 0.09 * (0.8 + 0.2 * flicker);
    const core = ctx.createRadialGradient(dom.x, dom.y, 0, dom.x, dom.y, coreR);
    core.addColorStop(0, `rgba(255,240,200,${0.65 * flicker})`);
    core.addColorStop(0.5, `rgba(255,180,80,${0.40 * flicker})`);
    core.addColorStop(1, 'rgba(255,120,40,0)');
    ctx.fillStyle = core;
    ctx.beginPath(); ctx.arc(dom.x, dom.y, coreR, 0, TAU); ctx.fill();
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

  // Hover/selected ring — dashed outline so you know you're on one. A domain
  // that's a NEIGHBOR of the active node (e.g. the domain a selected repo hangs
  // off of) gets the same ring so it visibly lights up at the far end of the
  // connection line — previously it only stayed bright while others dimmed, with
  // no highlight of its own, because the ring was gated on the domain BEING the
  // pinned node (a pinned repo's id never matches a domain id).
  const isNeighbor = !isActiveDom && inNb;
  if (isActiveDom || isNeighbor) {
    // The dashed border ring dims with the SAME tier as the nebula (× dimFactor),
    // so a connected domain's ring reads as secondary to the active domain's —
    // active 1.0 → 0.35, connected 0.55 → ~0.19. (It was slightly brighter than
    // the active ring before, which fought the 3-tier emphasis.)
    ctx.strokeStyle = rgba(r, g, b, 0.35 * dimFactor);
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

/** Find a node (entity | domain | repo) by its rendered id — O(1) via the maps.
 *  entity ids are raw; domains are 'dom:'+path; collections are
 *  'collection:'+collectionId (WorldState builds them with that prefix). */
function _findNode(state, id) {
  if (state.entities.has(id)) return state.entities.get(id);
  if (id.startsWith('dom:')) return state.domains.get(id.slice(4)) || null;
  if (id.startsWith('collection:')) return state.collections.get(id.slice(11)) || null;
  return null;
}

/** Repo ids linked to `collectionId` — reads the adjacency index built at load. */
function _connectedRepoIds(state, collectionId) {
  return state.collectionNeighbors?.get(collectionId) || _EMPTY_SET;
}
const _EMPTY_SET = new Set();

/** Compute the 1-hop neighborhood id set for the active (hovered/pinned) node:
 *  entity → its domains + repos; domain → its entities + repos; repo → its
 *  entities + connected repos + domain. Uses the reverse indexes so it's a
 *  lookup, not a per-frame scan over all entities. */
export function getNeighborhood(state) {
  const activeId = state.pinnedId ?? state.hoveredId;
  if (!activeId) return null;
  const node = _findNode(state, activeId);
  if (!node) return null;

  const ids = new Set([activeId]);
  if (node.kind === 'entity') {
    for (const path of Object.keys(node.domainWeights || {})) {
      const dom = state.domains.get(path); if (dom) ids.add(dom.id);
    }
    for (const rid of Object.keys(node.collectionWeights || {})) {
      const repo = state.collections.get(rid); if (repo) ids.add(repo.id);
    }
  } else if (node.kind === 'domain') {
    for (const e of (state.domainEntities.get(node.path) || [])) ids.add(e.id);
    for (const [, r] of state.collections) if (r.domainPath === node.path) ids.add(r.id);
    // Connected domains via trade routes — but only the ones ABOVE the render
    // threshold, i.e. the same strongest set drawTradeRoutes actually draws lines
    // to (via _thinByWeight). Adding them lights them up (dashed ring, no dim) at
    // the far end of each drawn route, the way a selected repo lights up its domain.
    const routeLinks = [];
    for (const route of state.tradeRoutes) {
      if (route.source !== node.path && route.target !== node.path) continue;
      const otherPath = route.source === node.path ? route.target : route.source;
      const other = state.domains.get(otherPath);
      if (other) routeLinks.push({ other, route });
    }
    for (const { other } of _thinByWeight(routeLinks, l => l.route.weight)) ids.add(other.id);
  } else if (node.kind === 'collection') {
    for (const e of (state.collectionEntities.get(node.collectionId) || [])) ids.add(e.id);
    for (const rid of _connectedRepoIds(state, node.collectionId)) {
      const r = state.collections.get(rid); if (r) ids.add(r.id);
    }
    if (node.domainPath) { const d = state.domains.get(node.domainPath); if (d) ids.add(d.id); }
  }
  return ids;
}

/** Draw 1-hop neighborhood highlight lines from the hovered/selected node.
 *  Bounded to a single node's neighbors — replaces the old always-on
 *  entity→repo web (which stroked ~8k lines every frame at deep zoom). */
export function drawNeighborhoodLines(ctx, state, camera) {
  const activeId = state.pinnedId ?? state.hoveredId;
  if (!activeId) return;
  const node = _findNode(state, activeId);
  if (!node) return;

  const line = (ax, ay, bx, by, color, w) => {
    ctx.strokeStyle = color; ctx.lineWidth = w;
    ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
  };

  if (node.kind === 'entity') {
    const anbrs = state.attractNeighbors;
    if (anbrs && anbrs.size) {
      // Attract: lines to the fetched co-occurring ENTITIES (2nd-order), which
      // are what we framed — keeps the lines in-frame vs galaxy-wide domains.
      for (const id of anbrs) {
        if (id === node.id) continue;
        const e = state.entities.get(id); if (!e) continue;
        line(node.x, node.y, e.x, e.y, 'rgba(130,180,240,0.35)', 0.9);
      }
    } else {
      // Hover/select: lines to its parent domains + its repos.
      for (const path of Object.keys(node.domainWeights || {})) {
        const dom = state.domains.get(path);
        if (dom) line(node.x, node.y, dom.x, dom.y, 'rgba(100,160,220,0.3)', 0.8);
      }
      for (const rid of Object.keys(node.collectionWeights || {})) {
        const repo = state.collections.get(rid);
        // Skip a filtered-out repo (task 11b) — no line to an invisible node.
        if (repo && state.matchesFilter(repo)) line(node.x, node.y, repo.x, repo.y, 'rgba(224,160,48,0.35)', 0.8);
      }
    }
  } else if (node.kind === 'domain') {
    // Its entities: draw a line to EVERY one — seeing a domain's full spread (how
    // big its cluster is) is the point — but tier the opacity by strength so the
    // core members stand out from the long tail. The top 20% by weight (the
    // entity's share in THIS domain) render brighter; the rest stay light. All
    // still light up, so the cluster's size/shape reads at a glance.
    const ents = state.domainEntities.get(node.path) || [];
    const wOf = e => (e.domainWeights && e.domainWeights[node.path]) || 0;
    // 80th-percentile weight = the cutoff for the top 20% (sort primitives only;
    // cheaper than sorting the entity objects, and ties at the cutoff read bright).
    const sortedW = ents.map(wOf).sort((a, b) => b - a);
    const cutoff = sortedW.length ? sortedW[Math.max(0, Math.ceil(sortedW.length * 0.2) - 1)] : 0;
    for (const e of ents) {
      if (!state.matchesFilter(e)) continue;   // silo/kind filter (task 11b)
      const a = wOf(e) >= cutoff ? 0.22 : 0.06;    // top 20% brighter, tail lighter
      line(node.x, node.y, e.x, e.y, rgba(100, 160, 220, a), 0.4);
    }
    for (const [, r] of state.collections) {
      if (r.domainPath === node.path && state.matchesFilter(r)) line(node.x, node.y, r.x, r.y, 'rgba(224,160,48,0.3)', 0.8);
    }
  } else if (node.kind === 'collection') {
    // Its entities (gold, subtle) + connected repos + its domain.
    for (const e of (state.collectionEntities.get(node.collectionId) || [])) {
      if (state.matchesFilter(e)) line(node.x, node.y, e.x, e.y, 'rgba(224,160,48,0.18)', 0.5);
    }
    for (const rid of _connectedRepoIds(state, node.collectionId)) {
      const r = state.collections.get(rid);
      if (r && state.matchesFilter(r)) line(node.x, node.y, r.x, r.y, 'rgba(224,160,48,0.35)', 0.9);
    }
    if (node.domainPath) {
      const d = state.domains.get(node.domainPath);
      if (d) line(node.x, node.y, d.x, d.y, 'rgba(100,160,220,0.3)', 0.8);
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

// Weight-threshold a dense edge web to cut its long tail. Sort strongest-first,
// keep edges until they cover EDGE_COVERAGE of the total weight, but never more
// than clamp(round(EDGE_CAP_FRAC · n), EDGE_CAP_MIN, EDGE_CAP_MAX) — so a bigger
// web shows proportionally more, a small one shows few, and a runaway hub is
// bounded. Returns the kept edge objects (unchanged). Applied to the two dense
// domain↔domain / repo↔repo webs; the raw weights stay on state, only the
// rendering is thinned.
const EDGE_COVERAGE = 0.8;
const EDGE_CAP_FRAC = 0.20, EDGE_CAP_MIN = 5, EDGE_CAP_MAX = 20;
function _thinByWeight(edges, weightOf) {
  const n = edges.length;
  if (n <= EDGE_CAP_MIN) return edges.slice();
  const cap = Math.max(EDGE_CAP_MIN, Math.min(EDGE_CAP_MAX, Math.round(EDGE_CAP_FRAC * n)));
  const sorted = edges.slice().sort((a, b) => weightOf(b) - weightOf(a));
  const total = sorted.reduce((s, e) => s + Math.max(0, weightOf(e)), 0);
  const kept = [];
  let cum = 0;
  for (const e of sorted) {
    kept.push(e);
    cum += Math.max(0, weightOf(e));
    if (kept.length >= cap) break;                       // hard ceiling
    if (total > 0 && cum / total >= EDGE_COVERAGE) break;  // enough coverage
  }
  return kept;
}

/** Draw trade routes + traveling pulses — only visible at sector zoom */
export function drawTradeRoutes(ctx, state, camera, W, H) {
  // Static domain↔domain "trade routes" are drawn ONLY for the active (hovered or
  // pinned) domain, and only its strongest routes (weight-thinned) — domains
  // share entities so densely that even one hub domain has ~150 routes. Scoping
  // to the selection + thinning the tail makes each remaining route legible.
  // Traveling pulses (activity animations) below still play regardless.
  const activeId = state.pinnedId ?? state.hoveredId;
  const activeDomPath = (activeId && activeId.startsWith('dom:')) ? activeId.slice(4) : null;

  // Trade routes are sector-level detail (per the JSDoc): fade them in across the
  // galaxy→sector band so the zoomed-out overview stays clean — invisible below
  // ~0.30, full by ~0.45. (Pulses below still animate at any zoom.)
  const zoomFade = camera ? clamp((camera.zoom - 0.30) / 0.15, 0, 1) : 1;

  if (activeDomPath && zoomFade > 0) {
    // Viewport bounds — skip routes whose whole segment is off one edge.
    let vL = -Infinity, vR = Infinity, vT = -Infinity, vB = Infinity;
    if (camera && W && H) {
      const vhw = W / 2 / camera.zoom, vhh = H / 2 / camera.zoom;
      vL = camera.x - vhw; vR = camera.x + vhw; vT = camera.y - vhh; vB = camera.y + vhh;
    }
    // Gather this domain's routes with on-map endpoints, then keep only the
    // strongest (Pareto + cap). A hub domain's 150 routes collapse to ~16.
    const mine = [];
    for (const route of state.tradeRoutes) {
      if (route.source !== activeDomPath && route.target !== activeDomPath) continue;
      const srcDom = state.domains.get(route.source);
      const tgtDom = state.domains.get(route.target);
      if (srcDom && tgtDom) mine.push({ route, srcDom, tgtDom });
    }
    const kept = _thinByWeight(mine, m => m.route.weight);
    // Normalize opacity within the KEPT set so the strongest shown route reads
    // brightest (global max would leave a weakly-connected domain all-faint).
    const localMax = Math.max(1, ...kept.map(m => m.route.weight));
    ctx.setLineDash([8, 16]);
    for (const { route, srcDom, tgtDom } of kept) {
      if ((srcDom.x < vL && tgtDom.x < vL) || (srcDom.x > vR && tgtDom.x > vR) ||
          (srcDom.y < vT && tgtDom.y < vT) || (srcDom.y > vB && tgtDom.y > vB)) continue;

      const normWeight = route.weight / localMax;
      const a = (0.18 + normWeight * 0.32) * zoomFade;
      const lw = 0.8 + normWeight * 2.0;
      ctx.strokeStyle = rgba(0, 200, 180, a);
      ctx.lineWidth = lw;
      ctx.beginPath();
      ctx.moveTo(srcDom.x, srcDom.y);
      ctx.lineTo(tgtDom.x, tgtDom.y);
      ctx.stroke();
    }
    ctx.setLineDash([]);
  }

  // Draw traveling pulses (from state.pulses)
  for (const p of state.pulses) {
    // Support explicit fromX/fromY (entity→domain) or domain lookup (domain→domain)
    let ax, ay, bx, by;
    if (p.fromX !== undefined) {
      ax = p.fromX; ay = p.fromY;
      bx = p.toX; by = p.toY;
    } else {
      const srcDom = state.domains.get(p.source);
      const tgtDom = state.domains.get(p.target);
      if (!srcDom || !tgtDom) continue;
      ax = srcDom.x; ay = srcDom.y;
      bx = tgtDom.x; by = tgtDom.y;
    }

    const rawP = p.progress;
    const ep = rawP < 0.5 ? 2 * rawP * rawP : -1 + (4 - 2 * rawP) * rawP;
    const gf = sin(rawP * Math.PI);

    const px = ax + (bx - ax) * ep;
    const py = ay + (by - ay) * ep;

    // Entity→domain pulses are smaller and dimmer
    const isEntityPulse = p.fromX !== undefined;
    const bright = isEntityPulse ? 0.5 : 1.0;
    const scale = isEntityPulse ? 0.5 : 1.0;

    // Trail
    const trailP = max(0, rawP - 0.10);
    const tep = trailP < 0.5 ? 2 * trailP * trailP : -1 + (4 - 2 * trailP) * trailP;
    const tx = ax + (bx - ax) * tep;
    const ty = ay + (by - ay) * tep;
    const tg = ctx.createLinearGradient(tx, ty, px, py);
    tg.addColorStop(0, `rgba(255,255,255,0)`);
    tg.addColorStop(1, `rgba(255,255,255,${0.50 * gf * bright})`);
    ctx.strokeStyle = tg;
    ctx.lineWidth = 3 * scale;
    ctx.beginPath();
    ctx.moveTo(tx, ty);
    ctx.lineTo(px, py);
    ctx.stroke();

    // Dot
    const [pr, pg, pb] = p.col;
    const sz = (20 + gf * 12) * scale;
    const dg = ctx.createRadialGradient(px, py, 0, px, py, sz);
    dg.addColorStop(0, `rgba(255,255,255,${0.98 * gf * bright})`);
    dg.addColorStop(0.2, `rgba(${pr},${pg},${pb},${0.85 * gf * bright})`);
    dg.addColorStop(0.6, `rgba(${pr},${pg},${pb},${0.30 * gf * bright})`);
    dg.addColorStop(1, `rgba(${pr},${pg},${pb},0)`);
    ctx.fillStyle = dg;
    ctx.beginPath();
    ctx.arc(px, py, sz, 0, TAU);
    ctx.fill();

    // Arrival ripple (domain→domain only)
    if (!isEntityPulse && rawP > 0.82) {
      const tgtDom = state.domains.get(p.target);
      if (tgtDom) {
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
}

/** Draw entity stars — LOD based on zoom, viewport culling, neighborhood highlight */
export function drawEntityStars(ctx, state, camera, W, H, neighborhood) {
  const hasNeighborhood = neighborhood && neighborhood.size > 0;
  // Attract mode marks the selected entity's fetched co-occurring entities so
  // they render as visible stars (not dimmed) even when zoomed out — that's what
  // makes a dispersed neighborhood legible.
  const anbrs = state.attractNeighbors;
  const hasAttract = anbrs && anbrs.size > 0;
  const galaxyZoom = camera.zoom < 0.35;

  // Entities belong to L2 (system+, zoom >= 0.75). Below that they fade rather
  // than hard-cut, so a selection/attract neighborhood stays visible when zoomed
  // out. With nothing selected, still skip them at galaxy zoom (perf + clutter).
  if (camera.zoom < 0.75 && !hasNeighborhood && !hasAttract) return;

  // Smooth zoom fade: full above 0.75, easing to a 0.35 floor at 0.35 so stars
  // stay faintly visible when zoomed out instead of popping off.
  const zoomFade = 0.35 + 0.65 * clamp((camera.zoom - 0.35) / 0.4, 0, 1);

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
    // Silo/kind filter (task 11b) — hide non-matching entities outright rather
    // than dim them, ahead of neighborhood/LOD so a filtered-out node never
    // draws even when it's a hover/select neighbor.
    if (!state.matchesFilter(e)) continue;

    const inNeighborhood = (hasNeighborhood && neighborhood.has(e.id)) || (hasAttract && anbrs.has(e.id));

    // LOD filter — but always render neighborhood members
    if (!inNeighborhood) {
      if (galaxyZoom) continue;
      if (e.sourceCount < minSource && e.activityGlow < 0.1) continue;
      if (e.x < viewLeft || e.x > viewRight || e.y < viewTop || e.y > viewBottom) continue;
    }

    // Dim non-neighborhood when something is selected, brighten members
    const dimFactor = (hasNeighborhood || hasAttract) && !inNeighborhood ? 0.15 : 1.0;
    const brightFactor = inNeighborhood ? 1.3 : 1.0;

    const act = e.activityGlow;
    const sizeBoost = (1 + zoomScale * 1.5) * brightFactor;
    const bR = (e.radius * 0.6 + act * 3) * e.birthScale * sizeBoost;
    const [r, g, b] = hexRGB(e.color);
    const alpha = clamp((0.3 + act * 0.7 + zoomScale * 0.3) * dimFactor * brightFactor * zoomFade, 0, 1);

    if (sectorZoom) {
      // Multi-layer glow at sector zoom — 30% brighter than galaxy. The three
      // outer glow layers are pre-baked into a per-color sprite (see sprites.js);
      // we drawImage it scaled by bR and modulated by alpha instead of rebuilding
      // three gradients per entity per frame. Same look, a fraction of the cost.
      const sectorBright = SECTOR_BRIGHT;
      const sprite = entityGlowSprite(e.color);
      const half = (sprite.width * 0.5) * (bR / ENTITY_BR0); // sprite spans 5×bR ⇒ haloR
      ctx.globalAlpha = alpha;
      ctx.drawImage(sprite, e.x - half, e.y - half, half * 2, half * 2);
      ctx.globalAlpha = 1;

      // Layer 4: tiny hot white core — kept as a direct draw so it stays crisp.
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

/**
 * Repo layer — repo nodes binned inside their domain, repo↔repo edges,
 * and repo→domain tethers. Visible at sector zoom and deeper (>= 0.35).
 */
export function drawCollections(ctx, state, camera, W, H) {
  if (camera.zoom < 0.35) return;               // hidden at galaxy (L0)
  if (!state.collections || state.collections.size === 0) return;
  const fade = clamp((camera.zoom - 0.35) / 0.15, 0, 1);  // fade-in across the L0→L1 band

  // Viewport bounds (world space) for culling off-screen repo nodes below.
  const vhw = W / 2 / camera.zoom, vhh = H / 2 / camera.zoom;
  const vL = camera.x - vhw, vR = camera.x + vhw, vT = camera.y - vhh, vB = camera.y + vhh;

  const repoById = state.collections;
  const get = id => repoById.get(id);

  // repo→domain tethers (faint)
  for (const [, repo] of state.collections) {
    if (!state.matchesFilter(repo)) continue;   // silo/kind filter (task 11b)
    const dom = repo.domainPath ? state.domains.get(repo.domainPath) : null;
    if (!dom) continue;
    ctx.strokeStyle = rgba(224, 160, 48, 0.12 * fade);
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 6]);
    ctx.beginPath();
    ctx.moveTo(repo.x, repo.y);
    ctx.lineTo(dom.x, dom.y);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // repo↔repo manifest co-usage (solid) + shared-entity (dashed)
  const drawRepoEdge = (a, b, w, dashed) => {
    const ra = get(a), rb = get(b);
    if (!ra || !rb) return;
    // Silo/kind filter (task 11b) — an edge is only drawn when BOTH endpoints
    // are visible, so a filtered-out repo never anchors a stray line.
    if (!state.matchesFilter(ra) || !state.matchesFilter(rb)) return;
    // Dim + soft, matching the domain trade-route aesthetic (faint, thin, long dash).
    ctx.strokeStyle = rgba(224, 160, 48, (0.08 + Math.min(w / 20, 0.08)) * fade);
    ctx.lineWidth = 0.8;
    ctx.setLineDash(dashed ? [8, 16] : [10, 6]);
    ctx.beginPath();
    ctx.moveTo(ra.x, ra.y);
    ctx.lineTo(rb.x, rb.y);
    ctx.stroke();
    ctx.setLineDash([]);
  };
  // Thin the repo↔repo web to its strongest edges (same Pareto + cap as the
  // trade routes) so the always-on gold web reads as a backbone, not a full mesh.
  const repoWeb = [
    ...(state.collectionEdges || []).map(e => ({ e, dashed: false })),
    ...(state.collectionRoutes || []).map(e => ({ e, dashed: true })),
  ];
  for (const { e, dashed } of _thinByWeight(repoWeb, x => x.e.weight || 1)) {
    drawRepoEdge(e.source, e.target, e.weight || 1, dashed);
  }

  // repo nodes
  const activeId = state.pinnedId ?? state.hoveredId;
  for (const [, repo] of state.collections) {
    const bs = repo.birthScale || 0;
    if (bs < 0.05) continue;
    if (!state.matchesFilter(repo)) continue;   // silo/kind filter (task 11b)
    const R = repo.radius * bs;
    // Viewport cull — generous margin covers the outer cloud (~R*2.4), spikes,
    // and the label (which can extend well past the radius) so nothing pops out
    // at the edge.
    const m = R * 3 + 140;
    if (repo.x + m < vL || repo.x - m > vR || repo.y + m < vT || repo.y - m > vB) continue;
    const [r, g, b] = hexRGB(repo.color);
    const active = activeId === repo.id;
    const a = fade * (active ? 1 : 0.9);

    // Layered star effect — same construction as a domain nebula (offset
    // clouds → wide halo → bright core → spikes), tinted gold so it still
    // reads as a repo, so it matches the visual language of the graph.
    const bright = (active ? 1.3 : 1.0) * a;
    const breathe = 0.94 + 0.06 * sin(state.tick * 0.001 + repo.phase);
    const rot = repo.phase;
    const coreR = R * 0.4;

    // offset cloud layers
    for (let i = 0; i < 4; i++) {
      const angle = rot * (1 - i * 0.15) + i * 1.4;
      const lr = R * (2.4 - i * 0.15);
      const ox = cos(angle) * R * 0.1, oy = sin(angle) * R * 0.08;
      const baseA = (0.06 - i * 0.008) * bs * a;
      const gr = ctx.createRadialGradient(repo.x + ox, repo.y + oy, R * 0.2, repo.x + ox, repo.y + oy, lr);
      gr.addColorStop(0, rgba(r, g, b, 0));
      gr.addColorStop(0.12, rgba(r, g, b, baseA * 1.8));
      gr.addColorStop(0.5, rgba(r, g, b, baseA));
      gr.addColorStop(1, rgba(r, g, b, 0));
      ctx.fillStyle = gr;
      ctx.beginPath(); ctx.arc(repo.x + ox, repo.y + oy, lr, 0, TAU); ctx.fill();
    }

    // wide halo
    const wh = ctx.createRadialGradient(repo.x, repo.y, 0, repo.x, repo.y, R * 1.2);
    wh.addColorStop(0, rgba(r, g, b, 0.2 * bright));
    wh.addColorStop(0.3, rgba(r, g, b, 0.08 * bright));
    wh.addColorStop(1, rgba(r, g, b, 0));
    ctx.fillStyle = wh;
    ctx.beginPath(); ctx.arc(repo.x, repo.y, R * 1.2, 0, TAU); ctx.fill();

    // bright core (gold-white) — the shadowBlur glow is pre-baked into a sprite
    // (see sprites.js) and drawImage'd, scaled by coreR and pulsed via globalAlpha,
    // instead of running a Gaussian blur per repo per frame. Same gold glow, far
    // cheaper. (The breathing spikes below stay direct — they animate in shape.)
    const rcSprite = repoCoreSprite(repo.color);
    const rcHalf = (rcSprite.width * 0.5) * (coreR / REPO_CORE0);
    ctx.globalAlpha = min(1, bright * breathe);
    ctx.drawImage(rcSprite, repo.x - rcHalf, repo.y - rcHalf, rcHalf * 2, rcHalf * 2);
    ctx.globalAlpha = 1;

    // spikes (light rays)
    const spikeLen = R * 1.6, spikeA = bright * 0.4 * breathe;
    for (let s = 0; s < 4; s++) {
      const ang = s * PI / 2;
      const x2 = repo.x + cos(ang) * spikeLen, y2 = repo.y + sin(ang) * spikeLen;
      const spg = ctx.createLinearGradient(repo.x, repo.y, x2, y2);
      spg.addColorStop(0, `rgba(255,240,210,${spikeA})`);
      spg.addColorStop(0.3, rgba(r, g, b, spikeA * 0.5));
      spg.addColorStop(1, rgba(r, g, b, 0));
      ctx.strokeStyle = spg;
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(repo.x, repo.y); ctx.lineTo(x2, y2); ctx.stroke();
    }

    // dashed ring only when active/hovered (matches domain behavior)
    if (active) {
      ctx.strokeStyle = rgba(255, 220, 150, 0.4);
      ctx.lineWidth = 1.5;
      ctx.setLineDash([6, 10]);
      ctx.beginPath(); ctx.arc(repo.x, repo.y, R * 1.6, 0, TAU); ctx.stroke();
      ctx.setLineDash([]);
    }

    // label
    if (camera.zoom >= 0.4) {
      ctx.fillStyle = rgba(255, 235, 190, a);
      ctx.font = `14px 'Courier New', monospace`;
      ctx.textAlign = 'center';
      ctx.fillText('▣ ' + repo.label, repo.x, repo.y - R * 1.8 - 8);
      ctx.textAlign = 'start';
    }
  }
}

/**
 * Entity→repo tethers — faint lines from each entity to the repo it belongs to.
 * L2 only (zoom >= 0.75), so entities visibly hang off their repo, not the domain.
 */
export function drawEntityRepoTethers(ctx, state, camera) {
  if (camera.zoom < 0.75) return;
  const activeId = state.pinnedId ?? state.hoveredId;
  for (const [, e] of state.entities) {
    const rw = e.collectionWeights || {};
    for (const [rid, w] of Object.entries(rw)) {
      const repo = state.collections.get(rid);
      if (!repo) continue;
      const hot = activeId === e.id || activeId === repo.id;
      ctx.strokeStyle = rgba(224, 160, 48, (hot ? 0.4 : 0.10) * Math.min(1, w + 0.3));
      ctx.lineWidth = hot ? 1.4 : 0.6;
      ctx.beginPath();
      ctx.moveTo(e.x, e.y);
      ctx.lineTo(repo.x, repo.y);
      ctx.stroke();
    }
  }
}
