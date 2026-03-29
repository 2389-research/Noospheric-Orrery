/**
 * World state — domains, entities, clusters, activity.
 * Single source of truth for all renderers.
 */

import { WORLD_W, WORLD_H, sqrt, random, hypot, assignDomainColors, blendColors, hexRGB, rnd, TAU } from './utils.js';

export class WorldState {
  constructor() {
    this.domains = new Map();    // path → domain node
    this.entities = new Map();   // id → entity node
    this.clusters = [];          // [{id, domainPaths, centroidX, centroidY, radius}]
    this.tradeRoutes = [];       // [{source, target, weight}]
    this.domainColors = {};      // path → hex
    this.tick = 0;

    // Selection
    this.hoveredId = null;
    this.pinnedId = null;

    // Raw data
    this.graphData = null;

    // Ambient pulse system
    this.pulses = [];
    this.nextPulseTime = 0;
    this.pulseInterval = 600;
  }

  get activeId() {
    return this.pinnedId ?? this.hoveredId;
  }

  /** Load from /graph API response */
  loadGraphData(data) {
    this.graphData = data;
    this.domains.clear();
    this.entities.clear();

    // Compute colors
    const domainList = Object.keys(data.domain_positions).map(path => ({
      path,
      spec_version: data.domain_specs?.[path]?.spec_version ?? null,
    }));
    this.domainColors = assignDomainColors(domainList);

    // Also store per-domain from API colors as fallback
    if (data.region_colors) {
      for (const [path, color] of Object.entries(data.region_colors)) {
        if (!this.domainColors[path]) {
          this.domainColors[path] = color;
        }
      }
    }

    // Create domain nodes in world space
    const PADDING = 0.08;
    for (const [path, pos] of Object.entries(data.domain_positions)) {
      const vc = data.domain_video_counts?.[path] || 0;
      const isSub = (data.subdomains || []).includes(path);
      const specs = data.domain_specs || {};
      const hasSpec = specs[path] && specs[path].spec_version > 0;

      // UMAP → world space
      const wx = (PADDING + pos.x * (1 - 2 * PADDING)) * WORLD_W;
      const wy = (PADDING + pos.y * (1 - 2 * PADDING)) * WORLD_H;

      // Compute maturity
      const allPaths = Object.keys(data.domain_positions);
      const subdoms = allPaths.filter(p => p.startsWith(path + '/') && p !== path);
      let maturity = 0;
      if (subdoms.length === 0) {
        maturity = hasSpec ? 1.0 : 0.0;
      } else {
        const subWithSpec = subdoms.filter(p => specs[p] && specs[p].spec_version > 0).length;
        const subCoverage = subWithSpec / subdoms.length;
        maturity = hasSpec ? 0.5 + subCoverage * 0.5 : subCoverage * 0.4;
      }

      const isSimmering = (data.active_simmers || []).includes(path);
      const radius = isSub ? 60 + sqrt(vc) * 20 : 120 + sqrt(vc) * 35;

      this.domains.set(path, {
        id: 'dom:' + path,
        kind: 'domain',
        path,
        label: isSub ? path.split('/').pop() : path,
        color: this.domainColors[path] || '#81d4fa',
        radius,
        worldX: wx,
        worldY: wy,
        x: wx, y: wy,  // current position (after repulsion)
        docCount: vc,
        maturity,
        specVersion: hasSpec ? specs[path].spec_version : 0,
        entityCount: 0, // populated after entities are loaded
        simmering: isSimmering,
        isSubdomain: isSub,
        phase: random() * TAU,
        rot: random() * TAU,
        birthScale: 0,
        activityGlow: 0,
      });
    }

    // Enforce minimum separation
    this._enforceMinSeparation(400, 200);

    // Compute clusters
    this._computeClusters(600);

    // Create entity nodes
    for (const ent of (data.entities || [])) {
      const dw = ent.domainWeights || {};
      const domNames = Object.keys(dw);
      if (!domNames.length) continue;

      // Position: weighted average of domain positions
      let sx = 0, sy = 0, tw = 0;
      const domColors = [], domWeights = [];
      for (const [dname, w] of Object.entries(dw)) {
        const dom = this.domains.get(dname);
        if (!dom) continue;
        // Cube weights for symmetry breaking
        const cw = w * w * w;
        sx += dom.x * cw;
        sy += dom.y * cw;
        tw += cw;
        domColors.push(dom.color);
        domWeights.push(w);
      }
      if (tw === 0) continue;
      sx /= tw; sy /= tw;

      const vc = ent.videoCount || 0;
      const color = domColors.length > 1 ? blendColors(domColors, domWeights) : domColors[0];

      this.entities.set(ent.entityId || ('ent:' + ent.name), {
        id: ent.entityId || ('ent:' + ent.name),
        kind: 'entity',
        name: ent.name,
        label: ent.name,
        type: ent.type,
        color,
        radius: 2 + Math.min(sqrt(vc) * 0.8, 8),
        worldX: sx + rnd(-30, 30),
        worldY: sy + rnd(-30, 30),
        x: sx + rnd(-30, 30),
        y: sy + rnd(-30, 30),
        vx: 0, vy: 0,
        sourceCount: vc,
        domainWeights: dw,
        phase: random() * TAU,
        birthScale: 0,
        stability: Math.min(0.9, 0.3 * Math.log(vc + 1) / Math.log(30)),
        activityGlow: 0,
      });
    }

    // Entity repulsion — push overlapping entities apart
    this._spreadEntities(30, 50);

    // Count entities per domain
    for (const [, e] of this.entities) {
      for (const path of Object.keys(e.domainWeights || {})) {
        const dom = this.domains.get(path);
        if (dom) dom.entityCount++;
      }
    }

    // Trade routes
    this.tradeRoutes = (data.trade_routes || []).map(r => ({
      source: r.source,
      target: r.target,
      weight: r.weight,
      pulseStart: null,
      pulseDuration: 900,
    }));

    // Reset ambient pulses on data reload
    this.pulses = [];
    this.nextPulseTime = 0;
  }

  /** Push domains apart to enforce minimum separation */
  _enforceMinSeparation(minDist, iterations) {
    const doms = [...this.domains.values()];
    for (let iter = 0; iter < iterations; iter++) {
      for (let i = 0; i < doms.length; i++) {
        for (let j = i + 1; j < doms.length; j++) {
          const a = doms[i], b = doms[j];
          const dx = b.x - a.x, dy = b.y - a.y;
          const dist = hypot(dx, dy) || 1;
          if (dist < minDist) {
            const push = (minDist - dist) / 2;
            const nx = dx / dist, ny = dy / dist;
            a.x -= nx * push * 0.5;
            a.y -= ny * push * 0.5;
            b.x += nx * push * 0.5;
            b.y += ny * push * 0.5;
          }
        }
      }
    }
    // Update worldX/Y to match
    for (const d of doms) {
      d.worldX = d.x;
      d.worldY = d.y;
    }
  }

  /** Group nearby domains into clusters */
  _computeClusters(threshold) {
    const doms = [...this.domains.values()];
    const assigned = new Set();
    this.clusters = [];

    for (let i = 0; i < doms.length; i++) {
      if (assigned.has(i)) continue;
      const members = [i];
      assigned.add(i);

      for (let j = i + 1; j < doms.length; j++) {
        if (assigned.has(j)) continue;
        const dx = doms[i].x - doms[j].x;
        const dy = doms[i].y - doms[j].y;
        if (hypot(dx, dy) < threshold) {
          members.push(j);
          assigned.add(j);
        }
      }

      // Compute centroid and radius
      let cx = 0, cy = 0;
      for (const mi of members) {
        cx += doms[mi].x;
        cy += doms[mi].y;
      }
      cx /= members.length;
      cy /= members.length;

      let maxR = 0;
      for (const mi of members) {
        const dist = hypot(doms[mi].x - cx, doms[mi].y - cy);
        maxR = Math.max(maxR, dist + doms[mi].radius * 2);
      }

      this.clusters.push({
        id: `cluster-${this.clusters.length}`,
        domainPaths: members.map(mi => doms[mi].path),
        centroidX: cx,
        centroidY: cy,
        radius: Math.max(maxR, 200),
        members: members.map(mi => doms[mi]),
      });
    }
  }

  /** Push overlapping entities apart using spatial grid for performance */
  _spreadEntities(minDist, iterations) {
    const ents = [...this.entities.values()];
    if (ents.length < 2) return;

    const cellSize = minDist * 2;

    for (let iter = 0; iter < iterations; iter++) {
      // Build spatial grid
      const grid = {};
      for (const e of ents) {
        const cx = Math.floor(e.x / cellSize);
        const cy = Math.floor(e.y / cellSize);
        const key = `${cx},${cy}`;
        (grid[key] ??= []).push(e);
      }

      // Check neighbors in adjacent cells
      for (const e of ents) {
        const cx = Math.floor(e.x / cellSize);
        const cy = Math.floor(e.y / cellSize);

        for (let dx = -1; dx <= 1; dx++) {
          for (let dy = -1; dy <= 1; dy++) {
            const neighbors = grid[`${cx + dx},${cy + dy}`];
            if (!neighbors) continue;

            for (const other of neighbors) {
              if (other === e) continue;
              const ddx = e.x - other.x;
              const ddy = e.y - other.y;
              const dist = hypot(ddx, ddy) || 0.1;
              if (dist < minDist) {
                const push = (minDist - dist) / 2 * 0.3;
                const nx = ddx / dist, ny = ddy / dist;
                e.x += nx * push;
                e.y += ny * push;
                other.x -= nx * push;
                other.y -= ny * push;
              }
            }
          }
        }
      }
    }

    // Update worldX/Y
    for (const e of ents) {
      e.worldX = e.x;
      e.worldY = e.y;
    }
  }

  /** Update per-frame state */
  update(dt) {
    this.tick++;
    const now = performance.now();

    // Grow birthScale
    for (const d of this.domains.values()) {
      if (d.birthScale < 1) d.birthScale = Math.min(1, d.birthScale + 0.015);
      // Decay activity — matches reference: 0.0015 * dt
      if (d.activityGlow > 0) d.activityGlow = Math.max(0, d.activityGlow - 0.0015 * dt);
      d.rot += 0.0003;
    }

    for (const e of this.entities.values()) {
      if (e.birthScale < 1) e.birthScale = Math.min(1, e.birthScale + 0.012);
      if (e.activityGlow > 0) e.activityGlow = Math.max(0, e.activityGlow - 0.0015 * dt);
    }

    // Update active pulses
    this.pulses = this.pulses.filter(p => p.progress < 1);
    for (const p of this.pulses) {
      p.progress += p.speed;
      // Boost destination domain on arrival
      if (p.progress >= 0.82 && !p.arrivedFlag) {
        p.arrivedFlag = true;
        const tgtDom = this.domains.get(p.target);
        if (tgtDom) tgtDom.activityGlow = Math.min(1, tgtDom.activityGlow + 0.5);
      }
    }

    // Pulses are only spawned by search glow — no ambient firing
  }

  /** Trigger search glow — cascaded timing per animation spec */
  triggerSearchGlow(entityNames) {
    const hitEntities = [];
    const hitDomainPaths = new Set();

    // Find hit entities (preserve search ranking order)
    for (const name of entityNames) {
      const nameLower = name.toLowerCase();
      for (const [, e] of this.entities) {
        if (e.label.toLowerCase() === nameLower) {
          hitEntities.push(e);
          if (e.domainWeights) {
            for (const path of Object.keys(e.domainWeights)) hitDomainPaths.add(path);
          }
          break;
        }
      }
    }

    if (!hitEntities.length) return;

    // t=0: Flash entities (subtle, staggered)
    hitEntities.forEach((e, i) => {
      setTimeout(() => {
        e.activityGlow = Math.min(1.0, e.activityGlow + 0.5);
      }, i * 60);
    });

    // t=80ms: Brighten top 5 hit domains (not all)
    setTimeout(() => {
      // Rank domains by how many hit entities touch them
      const domScores = {};
      for (const path of hitDomainPaths) {
        domScores[path] = hitEntities.filter(e =>
          e.domainWeights && path in e.domainWeights
        ).length;
      }
      const topDomains = [...hitDomainPaths]
        .sort((a, b) => (domScores[b] || 0) - (domScores[a] || 0))
        .slice(0, 5);

      for (const path of topDomains) {
        const dom = this.domains.get(path);
        if (dom) dom.activityGlow = Math.min(1.0, dom.activityGlow + 0.45);
      }
      // Replace hitDomainPaths for pulse firing below
      hitDomainPaths.clear();
      for (const p of topDomains) hitDomainPaths.add(p);
    }, 80);

    // t=250ms: Fire route pulses between hit domains
    setTimeout(() => {
      // Score routes by hit density
      const domainHitCount = {};
      for (const e of hitEntities) {
        if (e.domainWeights) {
          for (const [path, w] of Object.entries(e.domainWeights)) {
            domainHitCount[path] = (domainHitCount[path] || 0) + w;
          }
        }
      }

      const candidates = [];
      for (const route of this.tradeRoutes) {
        if (hitDomainPaths.has(route.source) && hitDomainPaths.has(route.target)) {
          const score = (domainHitCount[route.source] || 0) + (domainHitCount[route.target] || 0);
          candidates.push({ route, score });
        }
      }
      // Sort by score, shuffle ties to avoid alphabetical spatial bias
      candidates.sort((a, b) => b.score - a.score || (random() - 0.5));

      // Cap at 4 pulses — enough to show activity without chaos
      candidates.slice(0, 4).forEach((c, i) => {
        const srcDom = this.domains.get(c.route.source);
        if (srcDom) {
          setTimeout(() => {
            this.pulses.push({
              source: c.route.source,
              target: c.route.target,
              col: hexRGB(srcDom.color),
              progress: 0,
              speed: 0.008,
              arrivedFlag: false,
            });
          }, i * 150);
        }
      });
    }, 250);

    // t=900ms: Arrival — destination domains get secondary pulse
    setTimeout(() => {
      for (const path of hitDomainPaths) {
        const dom = this.domains.get(path);
        if (dom) dom.activityGlow = Math.min(1.0, dom.activityGlow + 0.4);
      }
    }, 900);
  }
}
