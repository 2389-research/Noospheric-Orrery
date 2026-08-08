"use client";

// Device-local screensaver preferences. A screensaver setting is inherently
// per-display (the kiosk TV vs a laptop), so these live in localStorage, not on
// the server. Read by the orrery view (idle timer, beat, fps, scale) and the
// Magos overlay.
import { useCallback, useEffect, useState } from "react";

export interface ScreensaverSettings {
  idleMinutes: number;   // no input for this long → attract mode starts
  beatSeconds: number;   // interval between camera hops
  magos: boolean;        // show the Magos Lex commentary overlay
  fps: boolean;          // show the in-viz FPS meter
  scale: number;         // render-resolution fraction (1 = native)
}

export const DEFAULT_SCREENSAVER_SETTINGS: ScreensaverSettings = {
  idleMinutes: 5,
  beatSeconds: 13,
  magos: true,
  fps: false,
  scale: 1,
};

const KEY = "orrery.screensaver";
const CHANGE_EVENT = "orrery-screensaver-change";

/** Coerce one stored field, falling back to the default when it is not the right type.
 *
 *  localStorage is user-writable and survives format changes, so a spread of raw JSON
 *  trusts whatever is there. A string or null `idleMinutes` reaches
 *  `Math.max(1, idleMinutes) * 60 * 1000` as NaN, setTimeout treats NaN as 0, and
 *  attract mode starts instantly and cannot be escaped — the screensaver equivalent of
 *  a crash loop. */
function num(v: unknown, fallback: number): number {
  const n = typeof v === "string" ? Number(v) : v;
  return typeof n === "number" && Number.isFinite(n) ? n : fallback;
}

function bool(v: unknown, fallback: boolean): boolean {
  return typeof v === "boolean" ? v : fallback;
}

export function loadScreensaverSettings(): ScreensaverSettings {
  if (typeof window === "undefined") return DEFAULT_SCREENSAVER_SETTINGS;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return DEFAULT_SCREENSAVER_SETTINGS;
    const parsed = JSON.parse(raw) as Partial<Record<keyof ScreensaverSettings, unknown>>;
    const d = DEFAULT_SCREENSAVER_SETTINGS;
    return {
      idleMinutes: num(parsed.idleMinutes, d.idleMinutes),
      beatSeconds: num(parsed.beatSeconds, d.beatSeconds),
      scale: num(parsed.scale, d.scale),
      magos: bool(parsed.magos, d.magos),
      fps: bool(parsed.fps, d.fps),
    };
  } catch {
    return DEFAULT_SCREENSAVER_SETTINGS;
  }
}

/**
 * Reactive access to the screensaver settings. Starts from defaults on the
 * server / first paint (no hydration mismatch), then loads the stored value on
 * mount and re-reads whenever any consumer updates them (same-tab custom event
 * + cross-tab `storage` event).
 */
export function useScreensaverSettings(): [
  ScreensaverSettings,
  (patch: Partial<ScreensaverSettings>) => void,
] {
  const [settings, setSettings] = useState<ScreensaverSettings>(
    DEFAULT_SCREENSAVER_SETTINGS,
  );

  useEffect(() => {
    setSettings(loadScreensaverSettings());
    const sync = () => setSettings(loadScreensaverSettings());
    window.addEventListener(CHANGE_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(CHANGE_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  const update = useCallback((patch: Partial<ScreensaverSettings>) => {
    const next = { ...loadScreensaverSettings(), ...patch };
    try {
      window.localStorage.setItem(KEY, JSON.stringify(next));
    } catch {
      /* private mode / quota — settings just won't persist */
    }
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }, []);

  return [settings, update];
}
