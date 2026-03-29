/**
 * Camera system — zoom, pan, flyTo animation.
 * World space is 5000x5000. Camera defines viewport into world.
 */

import { clamp, getCurrentLevel } from './utils.js';

export class Camera {
  constructor() {
    this.x = 0;       // world-space center x
    this.y = 0;       // world-space center y
    this.zoom = 0.18;  // start zoomed out to see full galaxy
    this.targetX = 0;
    this.targetY = 0;
    this.targetZoom = 0.18;
    this.flying = false;
    this.flyStart = 0;
    this.flyDuration = 800;
    this.flyStartX = 0;
    this.flyStartY = 0;
    this.flyStartZoom = 0;

    // Drag state
    this.dragging = false;
    this.didDrag = false;
    this.dragStart = { x: 0, y: 0 };
    this.dragCamStart = { x: 0, y: 0 };
  }

  get level() {
    return getCurrentLevel(this.zoom);
  }

  /** Convert screen coords to world coords */
  screenToWorld(sx, sy, W, H) {
    return {
      x: (sx - W / 2) / this.zoom + this.x,
      y: (sy - H / 2) / this.zoom + this.y,
    };
  }

  /** Convert world coords to screen coords */
  worldToScreen(wx, wy, W, H) {
    return {
      x: (wx - this.x) * this.zoom + W / 2,
      y: (wy - this.y) * this.zoom + H / 2,
    };
  }

  /** Apply camera transform to canvas context */
  applyTransform(ctx, W, H) {
    ctx.translate(W / 2, H / 2);
    ctx.scale(this.zoom, this.zoom);
    ctx.translate(-this.x, -this.y);
  }

  /** Animate camera to target position */
  flyTo(x, y, zoom, duration = 800) {
    this.flyStartX = this.x;
    this.flyStartY = this.y;
    this.flyStartZoom = this.zoom;
    this.targetX = x;
    this.targetY = y;
    this.targetZoom = zoom;
    this.flyStart = performance.now();
    this.flyDuration = duration;
    this.flying = true;
  }

  /** Update camera each frame */
  update() {
    if (!this.flying) return;

    const elapsed = performance.now() - this.flyStart;
    const p = clamp(elapsed / this.flyDuration, 0, 1);

    // Ease-in-out cubic
    const ep = p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;

    this.x = this.flyStartX + (this.targetX - this.flyStartX) * ep;
    this.y = this.flyStartY + (this.targetY - this.flyStartY) * ep;
    this.zoom = this.flyStartZoom + (this.targetZoom - this.flyStartZoom) * ep;

    if (p >= 1) {
      this.flying = false;
      this.x = this.targetX;
      this.y = this.targetY;
      this.zoom = this.targetZoom;
    }
  }

  /** Handle mouse wheel zoom */
  handleWheel(e) {
    e.preventDefault();
    const factor = e.deltaY > 0 ? 0.9 : 1.1;
    this.zoom = clamp(this.zoom * factor, 0.05, 5);
  }

  /** Handle mouse down */
  handleMouseDown(e) {
    this.dragging = true;
    this.didDrag = false;
    this.dragStart = { x: e.clientX, y: e.clientY };
    this.dragCamStart = { x: this.x, y: this.y };
  }

  /** Handle mouse move for dragging */
  handleMouseDrag(e) {
    if (!this.dragging) return false;
    const dx = e.clientX - this.dragStart.x;
    const dy = e.clientY - this.dragStart.y;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) this.didDrag = true;
    this.x = this.dragCamStart.x - dx / this.zoom;
    this.y = this.dragCamStart.y - dy / this.zoom;
    return true;
  }

  /** Handle mouse up */
  handleMouseUp() {
    this.dragging = false;
  }
}
