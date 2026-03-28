"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const ENTITY_COLORS: Record<string, string> = {
  Person: "#378ADD", Organization: "#7F77DD", Product: "#1D9E75",
  Technology: "#BA7517", Event: "#D85A30", Concept: "#9c9a92", Location: "#5DCAA5",
};

export interface TradeRoutePanelData {
  source: string;
  target: string;
  sourceLabel: string;
  targetLabel: string;
  weight: number;
}

interface SharedEntity {
  id: string;
  canonical_name: string;
  type: string;
  source_count: number;
}

interface TradeRoutePanelContentProps {
  data: TradeRoutePanelData;
  onNavigateDomain: (path: string, name: string) => void;
  onNavigateEntity: (entity: { id: string; name: string; type: string; source_count: number }) => void;
}

export function TradeRoutePanelContent({ data, onNavigateDomain, onNavigateEntity }: TradeRoutePanelContentProps) {
  const [sharedEntities, setSharedEntities] = useState<SharedEntity[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const [sourceEnts, targetEnts] = await Promise.all([
          api.getEntities({ domain: data.source, limit: 200 }),
          api.getEntities({ domain: data.target, limit: 200 }),
        ]);
        const targetIds = new Set(targetEnts.map(e => e.id));
        const shared = sourceEnts.filter(e => targetIds.has(e.id))
          .sort((a, b) => b.source_count - a.source_count)
          .slice(0, 10);
        setSharedEntities(shared);
      } catch {
        setSharedEntities([]);
      } finally {
        setLoading(false);
      }
    })();
  }, [data.source, data.target]);

  const strengthLabel = data.weight >= 40 ? "strong connection" : data.weight >= 15 ? "moderate connection" : "weak connection";

  const sectionLabel: React.CSSProperties = {
    fontSize: 9, color: "rgba(140,200,255,0.6)", textTransform: "uppercase",
    letterSpacing: "0.08em", fontFamily: "'Courier New', monospace", marginBottom: 8, display: "block",
  };

  return (
    <div style={{ fontFamily: "'Courier New', monospace" }}>
      <div style={{ padding: "16px 16px 12px" }}>
        <div style={{ fontSize: 9, color: "rgba(0,200,180,0.7)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>
          Trade Route
        </div>
        <div style={{ fontSize: 14, color: "#e8eaf0", lineHeight: 1.2, marginBottom: 4 }}>
          weight: {data.weight} · {strengthLabel}
        </div>
      </div>

      {/* Two endpoints */}
      <div style={{ padding: "0 16px 12px", display: "flex", gap: 8 }}>
        <button
          onClick={() => onNavigateDomain(data.source, data.sourceLabel)}
          style={{
            flex: 1, background: "rgba(100,180,255,0.06)", border: "1px solid rgba(100,180,255,0.12)",
            borderRadius: 4, padding: "10px 8px", cursor: "pointer", textAlign: "center", fontFamily: "'Courier New', monospace",
          }}
        >
          <div style={{ fontSize: 11, color: "#e8eaf0" }}>{data.sourceLabel?.split("/").pop()}</div>
        </button>
        <div style={{ display: "flex", alignItems: "center", color: "rgba(0,200,180,0.5)", fontSize: 14 }}>↔</div>
        <button
          onClick={() => onNavigateDomain(data.target, data.targetLabel)}
          style={{
            flex: 1, background: "rgba(100,180,255,0.06)", border: "1px solid rgba(100,180,255,0.12)",
            borderRadius: 4, padding: "10px 8px", cursor: "pointer", textAlign: "center", fontFamily: "'Courier New', monospace",
          }}
        >
          <div style={{ fontSize: 11, color: "#e8eaf0" }}>{data.targetLabel?.split("/").pop()}</div>
        </button>
      </div>

      {/* Shared entities */}
      <div style={{ padding: "0 16px 16px", borderTop: "1px solid rgba(100,180,255,0.08)" }}>
        <div style={{ paddingTop: 12 }}>
          <span style={sectionLabel}>Shared Entities · {loading ? "..." : sharedEntities.length}</span>
          {loading ? (
            <div style={{ fontSize: 11, color: "rgba(140,200,255,0.6)", fontStyle: "italic" }}>loading...</div>
          ) : sharedEntities.length === 0 ? (
            <div style={{ fontSize: 11, color: "rgba(140,200,255,0.6)" }}>no shared entities found</div>
          ) : (
            sharedEntities.map((e) => (
              <button
                key={e.id}
                onClick={() => onNavigateEntity({ id: e.id, name: e.canonical_name, type: e.type, source_count: e.source_count })}
                style={{
                  display: "flex", alignItems: "center", gap: 8, width: "100%", background: "none",
                  border: "none", padding: "5px 0", cursor: "pointer", textAlign: "left",
                  borderBottom: "1px solid rgba(100,180,255,0.05)", fontFamily: "'Courier New', monospace",
                }}
              >
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: ENTITY_COLORS[e.type] || "#9c9a92", flexShrink: 0 }} />
                <span style={{ fontSize: 11, color: "rgba(200,215,235,0.85)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {e.canonical_name}
                </span>
                <span style={{ fontSize: 10, color: "rgba(140,200,255,0.6)", flexShrink: 0 }}>
                  {e.source_count} docs
                </span>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
