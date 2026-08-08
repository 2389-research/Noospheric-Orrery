"use client";

// Magos Lex screensaver overlay. During attract mode the galaxy iframe emits
// `attract_focus {nodeType, id, name}`; when the focused node is a domain or repo
// with pre-generated commentary, the Magos appears bottom-right showing one
// randomly chosen comment for the dwell (pose matches that comment). Purely
// additive and fail-silent: no commentary / setting off / entity focus →
// nothing renders, no error. Entities are out of scope for now (long tail),
// so their focus just clears the overlay.
import { useCallback, useEffect, useRef, useState } from "react";
import { isSameOriginMessage } from "@/lib/viz-message";

const POSE_PNG: Record<string, string> = {
  reading: "reading.png", galxy: "galxy.png", pointing: "pointing.png",
  thinking: "thinking.png", happy: "happy.png", sad: "sad.png", toaster: "toaster.png",
};
const POSE_EMOJI: Record<string, string> = {
  reading: "📖", galxy: "🌌", pointing: "👉", thinking: "🤔", happy: "😄", sad: "😔", toaster: "🍞",
};
const KIND_LABEL: Record<string, string> = {
  description: "Description", omnissiah: "For the Omnissiah", humor: "Levity",
};
const COMMENTED = new Set(["domain", "collection"]);

interface Comment { kind: string; text: string; pose: string; }

export function MagosOverlay({ enabled, workspaceId }: { enabled: boolean; workspaceId: string }) {
  // One comment per node view — no rotation. A random one of the node's three is
  // chosen on focus and held for the whole dwell.
  const [comment, setComment] = useState<Comment | null>(null);
  const [name, setName] = useState("");
  const fetchCtrl = useRef<AbortController | null>(null);
  const reqId = useRef(0);

  const clear = useCallback(() => {
    reqId.current++;
    fetchCtrl.current?.abort();
    setComment(null);
  }, []);

  useEffect(() => {
    if (!enabled) { clear(); return; }

    const onMsg = async (e: MessageEvent) => {
      if (!isSameOriginMessage(e)) return;
      const d = e.data;
      if (d?.type === "attract_focus") {
        if (!COMMENTED.has(d.nodeType) || !d.id) { clear(); return; }
        const my = ++reqId.current;
        fetchCtrl.current?.abort();
        const ctrl = new AbortController();
        fetchCtrl.current = ctrl;
        try {
          const r = await fetch(
            `/api/commentary/${encodeURIComponent(d.nodeType)}/${encodeURIComponent(d.id)}`,
            { headers: { "X-Workspace-Id": workspaceId }, signal: ctrl.signal },
          );
          if (my !== reqId.current) return;
          if (!r.ok) { setComment(null); return; }   // 404 / not generated yet → hide, no error
          const body = await r.json();
          if (my !== reqId.current) return;
          const cs: Comment[] = body?.comments || [];
          if (!cs.length) { setComment(null); return; }
          setName(d.name || "");
          // One random comment for this node view; it stays until the next node.
          setComment(cs[Math.floor(Math.random() * cs.length)]);
        } catch {
          /* abort or network — leave current state */
        }
      } else if (d?.type === "user_activity" || d?.type === "attract_stop") {
        clear();
      }
    };
    // Real interaction in the shell itself also dismisses the overlay.
    const onActivity = () => clear();
    const acts: (keyof WindowEventMap)[] = ["mousedown", "keydown", "touchstart"];

    window.addEventListener("message", onMsg);
    acts.forEach((ev) => window.addEventListener(ev, onActivity, { passive: true }));
    return () => {
      window.removeEventListener("message", onMsg);
      acts.forEach((ev) => window.removeEventListener(ev, onActivity));
      clear();
    };
  }, [enabled, workspaceId, clear]);

  if (!enabled || !comment) return null;
  const c = comment;

  return (
    <div
      aria-hidden
      style={{
        position: "fixed", right: 18, bottom: 60, zIndex: 40,
        display: "flex", alignItems: "flex-end", gap: 12, pointerEvents: "none",
      }}
    >
      <div
        style={{
          position: "relative", maxWidth: 340, marginBottom: 24,
          background: "rgba(14,17,28,0.85)", backdropFilter: "blur(8px)",
          WebkitBackdropFilter: "blur(8px)", border: "1px solid rgba(150,170,220,0.3)",
          borderRadius: 14, padding: "13px 15px 15px", color: "#e8ecf6",
          boxShadow: "0 10px 40px rgba(0,0,0,.5)",
        }}
      >
        <div style={{ fontSize: 9.5, letterSpacing: ".14em", textTransform: "uppercase", color: "#93a6d6", marginBottom: 7 }}>
          {(KIND_LABEL[c.kind] || c.kind) + "  " + (POSE_EMOJI[c.pose] || "")}
        </div>
        <div style={{ fontFamily: "'Iowan Old Style', Palatino, Georgia, serif", fontSize: 15, lineHeight: 1.5 }}>
          {c.text}
        </div>
        {name && (
          <div style={{ marginTop: 8, fontSize: 11, color: "#6d7ba0", borderTop: "1px solid rgba(150,170,220,0.15)", paddingTop: 6 }}>
            {name}
          </div>
        )}
        <div style={{
          position: "absolute", right: -9, bottom: 22, width: 18, height: 18,
          background: "rgba(14,17,28,0.85)", borderRight: "1px solid rgba(150,170,220,0.3)",
          borderBottom: "1px solid rgba(150,170,220,0.3)", transform: "rotate(-45deg)",
        }} />
      </div>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={`/mascot/${POSE_PNG[c.pose] || "galxy.png"}`}
        alt=""
        style={{ width: 196, height: "auto", filter: "drop-shadow(0 8px 22px rgba(0,0,0,.55))" }}
      />
    </div>
  );
}
