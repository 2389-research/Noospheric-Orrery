"use client";

// Gear button + popover for the device-local screensaver settings: idle timer,
// Magos Lex commentary, FPS meter, render scale, and beat speed.
import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import type { ScreensaverSettings } from "@/lib/screensaver-settings";

interface Props {
  settings: ScreensaverSettings;
  update: (patch: Partial<ScreensaverSettings>) => void;
}

const NUM = (v: string, fallback: number) => {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
};

export function ScreensaverSettingsPanel({ settings, update }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  const rowStyle: CSSProperties = {
    display: "flex", alignItems: "center", justifyContent: "space-between", gap: 14, padding: "7px 0",
  };
  const labelStyle: CSSProperties = { fontSize: 12.5, color: "#dfe3ef" };

  return (
    <div ref={ref} style={{ position: "fixed", top: 14, right: 14, zIndex: 60 }}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-label="Screensaver settings"
        aria-expanded={open}
        style={{
          cursor: "pointer", background: "rgba(14,17,28,0.75)", color: "#dfe3ef",
          border: "1px solid rgba(150,170,220,0.3)", borderRadius: 999,
          width: 34, height: 34, fontSize: 16, lineHeight: "32px", padding: 0,
        }}
      >
        ⚙
      </button>

      {open && (
        <div
          style={{
            position: "absolute", top: 42, right: 0, width: 260,
            background: "rgba(14,17,28,0.94)", backdropFilter: "blur(10px)",
            WebkitBackdropFilter: "blur(10px)", border: "1px solid rgba(150,170,220,0.28)",
            borderRadius: 12, padding: "12px 14px", color: "#dfe3ef",
            boxShadow: "0 16px 50px rgba(0,0,0,0.55)",
            fontFamily: "ui-monospace, Menlo, monospace",
          }}
        >
          <div style={{ fontSize: 10.5, letterSpacing: "0.18em", textTransform: "uppercase", color: "#e0a93b", marginBottom: 6 }}>
            Screensaver
          </div>

          <label style={rowStyle}>
            <span style={labelStyle}>Idle before start</span>
            <span>
              <input
                type="number" min={1} max={120} value={settings.idleMinutes}
                onChange={(e) => update({ idleMinutes: Math.min(120, Math.max(1, NUM(e.target.value, 5))) })}
                style={{ width: 52, background: "#0b0e18", color: "#dfe3ef", border: "1px solid rgba(150,170,220,0.3)", borderRadius: 6, padding: "3px 6px", textAlign: "right" }}
              /> <span style={{ fontSize: 11, color: "#8590aa" }}>min</span>
            </span>
          </label>

          <label style={rowStyle}>
            <span style={labelStyle}>Magos Lex commentary</span>
            <input type="checkbox" checked={settings.magos} onChange={(e) => update({ magos: e.target.checked })} />
          </label>

          <label style={rowStyle}>
            <span style={labelStyle}>FPS meter</span>
            <input type="checkbox" checked={settings.fps} onChange={(e) => update({ fps: e.target.checked })} />
          </label>

          <label style={rowStyle}>
            <span style={labelStyle}>Beat speed</span>
            <span>
              <input
                type="number" min={3} max={60} value={settings.beatSeconds}
                onChange={(e) => update({ beatSeconds: Math.min(60, Math.max(3, NUM(e.target.value, 13))) })}
                style={{ width: 52, background: "#0b0e18", color: "#dfe3ef", border: "1px solid rgba(150,170,220,0.3)", borderRadius: 6, padding: "3px 6px", textAlign: "right" }}
              /> <span style={{ fontSize: 11, color: "#8590aa" }}>s</span>
            </span>
          </label>

          <label style={rowStyle}>
            <span style={labelStyle}>Render scale</span>
            <select
              value={String(settings.scale)}
              onChange={(e) => update({ scale: NUM(e.target.value, 1) })}
              style={{ background: "#0b0e18", color: "#dfe3ef", border: "1px solid rgba(150,170,220,0.3)", borderRadius: 6, padding: "3px 6px" }}
            >
              <option value="1">1.0 (native)</option>
              <option value="0.75">0.75</option>
              <option value="0.66">0.66</option>
              <option value="0.5">0.5</option>
            </select>
          </label>

          <div style={{ fontSize: 10.5, color: "#6d7ba0", marginTop: 6, lineHeight: 1.4 }}>
            Saved on this device. Scale changes reload the view.
          </div>
        </div>
      )}
    </div>
  );
}
