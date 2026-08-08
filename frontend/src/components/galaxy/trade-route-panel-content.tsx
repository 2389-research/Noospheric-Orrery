"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ENTITY_COLORS } from "./entity-colors";

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

interface TypeGroup {
  type: string;
  count: number;
  examples: string[];
}

interface TradeRoutePanelContentProps {
  data: TradeRoutePanelData;
  onNavigateDomain: (path: string, name: string) => void;
  onNavigateEntity: (entity: { id: string; name: string; type: string; source_count: number }) => void;
}

function connectionStrength(weight: number): string {
  if (weight >= 40) return "strong";
  if (weight >= 15) return "moderate";
  return "weak";
}

export function TradeRoutePanelContent({ data, onNavigateDomain, onNavigateEntity }: TradeRoutePanelContentProps) {
  const [sharedEntities, setSharedEntities] = useState<SharedEntity[]>([]);
  const [sourceCount, setSourceCount] = useState(0);
  const [targetCount, setTargetCount] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const [sourceEnts, targetEnts] = await Promise.all([
          api.getEntities({ domain: data.source, limit: 300 }),
          api.getEntities({ domain: data.target, limit: 300 }),
        ]);
        setSourceCount(sourceEnts.length);
        setTargetCount(targetEnts.length);
        const targetIds = new Set(targetEnts.map(e => e.id));
        const shared = sourceEnts.filter(e => targetIds.has(e.id))
          .sort((a, b) => b.source_count - a.source_count);
        setSharedEntities(shared);
      } catch {
        setSharedEntities([]);
      } finally {
        setLoading(false);
      }
    })();
  }, [data.source, data.target]);

  const strength = connectionStrength(data.weight);

  // Overlap percentage relative to smaller domain
  const smallerCount = Math.min(sourceCount, targetCount);
  const smallerName = sourceCount < targetCount
    ? data.sourceLabel?.split("/").pop()
    : data.targetLabel?.split("/").pop();
  const overlapPct = smallerCount > 0 ? Math.round((sharedEntities.length / smallerCount) * 100) : 0;

  // Type breakdown
  const typeGroups: TypeGroup[] = [];
  if (sharedEntities.length > 0) {
    const byType: Record<string, SharedEntity[]> = {};
    for (const e of sharedEntities) {
      (byType[e.type] ??= []).push(e);
    }
    for (const [type, ents] of Object.entries(byType).sort((a, b) => b[1].length - a[1].length).slice(0, 4)) {
      typeGroups.push({
        type,
        count: ents.length,
        examples: ents.slice(0, 2).map(e => e.canonical_name),
      });
    }
  }

  const sectionLabel: React.CSSProperties = {
    fontSize: 9, color: "rgba(140,200,255,0.6)", textTransform: "uppercase",
    letterSpacing: "0.08em", fontFamily: "'Courier New', monospace", marginBottom: 8, display: "block",
  };

  const sectionStyle: React.CSSProperties = {
    padding: "0 16px 14px",
    borderTop: "1px solid rgba(100,180,255,0.08)",
    paddingTop: 12,
  };

  const srcShort = data.sourceLabel?.split("/").pop() ?? data.source;
  const tgtShort = data.targetLabel?.split("/").pop() ?? data.target;

  return (
    <div style={{ fontFamily: "'Courier New', monospace" }}>
      {/* Header */}
      <div style={{ padding: "16px 16px 12px" }}>
        <div style={{ fontSize: 9, color: "rgba(0,200,180,0.7)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>
          Trade Route · {strength}
        </div>
        <div style={{ fontSize: 16, color: "#e8eaf0", lineHeight: 1.2, marginBottom: 4 }}>
          {loading ? "..." : `${sharedEntities.length} entities shared`}
        </div>
      </div>

      {/* Domain endpoints */}
      <div style={{ padding: "0 16px 12px", display: "flex", gap: 8 }}>
        <button
          onClick={() => onNavigateDomain(data.source, data.sourceLabel)}
          style={{
            flex: 1, background: "rgba(100,180,255,0.06)", border: "1px solid rgba(100,180,255,0.12)",
            borderRadius: 4, padding: "10px 8px", cursor: "pointer", textAlign: "center", fontFamily: "'Courier New', monospace",
          }}
        >
          <div style={{ fontSize: 11, color: "#e8eaf0" }}>{srcShort}</div>
          <div style={{ fontSize: 9, color: "rgba(140,200,255,0.6)", marginTop: 2 }}>{sourceCount} entities</div>
        </button>
        <div style={{ display: "flex", alignItems: "center", color: "rgba(0,200,180,0.5)", fontSize: 14 }}>↔</div>
        <button
          onClick={() => onNavigateDomain(data.target, data.targetLabel)}
          style={{
            flex: 1, background: "rgba(100,180,255,0.06)", border: "1px solid rgba(100,180,255,0.12)",
            borderRadius: 4, padding: "10px 8px", cursor: "pointer", textAlign: "center", fontFamily: "'Courier New', monospace",
          }}
        >
          <div style={{ fontSize: 11, color: "#e8eaf0" }}>{tgtShort}</div>
          <div style={{ fontSize: 9, color: "rgba(140,200,255,0.6)", marginTop: 2 }}>{targetCount} entities</div>
        </button>
      </div>

      {/* Overlap stat */}
      {!loading && sharedEntities.length > 0 && (
        <div style={{ padding: "0 16px 12px", fontSize: 10, color: "rgba(200,215,235,0.85)", lineHeight: 1.6 }}>
          {sharedEntities.length} of {smallerCount} entities in {smallerName} ({overlapPct}%)
        </div>
      )}

      {/* What connects them — type breakdown */}
      {typeGroups.length > 0 && (
        <div style={sectionStyle}>
          <span style={sectionLabel}>What Connects Them</span>
          {typeGroups.map((group) => (
            <div key={group.type} style={{ display: "flex", alignItems: "baseline", gap: 8, padding: "3px 0" }}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: ENTITY_COLORS[group.type] || "#9c9a92", flexShrink: 0, marginTop: 4, display: "inline-block" }} />
              <span style={{ fontSize: 10, color: ENTITY_COLORS[group.type] || "#9c9a92", width: 75, flexShrink: 0 }}>{group.type}</span>
              <span style={{ fontSize: 10, color: "#e8eaf0", width: 20, flexShrink: 0 }}>{group.count}</span>
              <span style={{ fontSize: 9, color: "rgba(200,215,235,0.65)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {group.examples.join(", ")}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Shared entities */}
      <div style={sectionStyle}>
        <span style={sectionLabel}>Shared Entities{!loading ? ` · ${sharedEntities.length}` : ""}</span>
        {loading ? (
          <div style={{ fontSize: 11, color: "rgba(140,200,255,0.6)", fontStyle: "italic" }}>loading...</div>
        ) : sharedEntities.length === 0 ? (
          <div style={{ fontSize: 11, color: "rgba(140,200,255,0.6)" }}>
            No shared entities found.<br />
            <span style={{ fontSize: 9 }}>The weight reflects document co-occurrence but entity resolution is pending.</span>
          </div>
        ) : (
          <>
            {sharedEntities.slice(0, 5).map((e) => (
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
                <span style={{ fontSize: 10, color: "rgba(140,200,255,0.6)" }}>→</span>
              </button>
            ))}
            {sharedEntities.length > 5 && (
              <div style={{ fontSize: 9, color: "rgba(140,200,255,0.6)", padding: "6px 0" }}>
                + {sharedEntities.length - 5} more
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
