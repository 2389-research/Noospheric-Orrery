"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { getEntityColor } from "./entity-colors";
import type { CollectionPanelData, CollectionTopEntity } from "@/lib/types";

// Re-exported so `galaxy-panel` keeps importing it from here; the definition itself
// now lives in lib/types.ts alongside the rest of the API contract.
export type { CollectionPanelData };

interface CollectionPanelContentProps {
  data: CollectionPanelData;
  onNavigateEntity?: (entity: { id: string; name: string; type: string; source_count: number }) => void;
}

export function CollectionPanelContent({ data, onNavigateEntity }: CollectionPanelContentProps) {
  const accentColor = "#e0a030";
  const [summary, setSummary] = useState<string>("");
  const [topEntities, setTopEntities] = useState<CollectionTopEntity[]>([]);
  const [domain, setDomain] = useState<string | null>(data.domain ?? null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  // Fetch the grounded collection-level summary + top entities on selection.
  //
  // GalaxyPanel reuses this component across collections, so clicking B while A is
  // still in flight would let A's late response overwrite B's state — the panel then
  // shows one collection's title over another's summary. `cancelled` drops the stale
  // resolution. `domain` is reset from props on every change for the same reason: it
  // was only ever assigned when the response carried a truthy domain, so a collection
  // without one silently kept the PREVIOUS collection's domain on screen.
  //
  // EVERY field resets at the start, not just the ones the response overwrites. The
  // failure path is what makes this necessary: if B errors after A loaded, `loading`
  // clears but `summary`/`topEntities` still hold A's, so the panel renders A's content
  // under B's name — a wrong answer presented as a successful one, which is worse than
  // the error it is hiding.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    setSummary("");
    setTopEntities([]);
    setDomain(data.domain ?? null);
    (async () => {
      try {
        const res = await api.getCollectionSummary(data.id);
        if (cancelled) return;
        setSummary(res.summary ?? "");
        setTopEntities(res.top_entities ?? []);
        if (res.collection?.domain) setDomain(res.collection.domain);
      } catch {
        if (!cancelled) setError(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [data.id, data.domain]);

  const maxCount = topEntities.length > 0 ? topEntities[0].count : 1;

  const sectionLabel: React.CSSProperties = {
    fontSize: 9,
    color: "rgba(140,200,255,0.6)",
    textTransform: "uppercase",
    letterSpacing: "0.08em",
    fontFamily: "'Courier New', monospace",
    marginBottom: 8,
    display: "block",
  };

  const sectionStyle: React.CSSProperties = {
    padding: "14px 16px",
    borderBottom: "1px solid rgba(100,180,255,0.08)",
  };

  return (
    <div style={{ fontFamily: "'Courier New', monospace" }}>
      {/* Header */}
      <div style={{ padding: "16px 16px 12px" }}>
        <div style={{ fontSize: 9, color: "rgba(140,200,255,0.6)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>
          Collection
        </div>
        <div style={{ fontSize: 18, color: accentColor, lineHeight: 1.2, marginBottom: 4 }}>
          {data.name}
        </div>
        {domain && (
          <div style={{ fontSize: 11, color: "rgba(100,180,255,0.35)" }}>
            {domain.replace(/\//g, " / ")}
          </div>
        )}
      </div>

      {/* Stats strip */}
      <div style={{ ...sectionStyle, display: "flex", gap: 8, flexWrap: "wrap" }}>
        <div style={{
          padding: "4px 8px",
          border: "1px solid rgba(100,180,255,0.15)",
          borderRadius: 3,
          fontSize: 11,
          color: "rgba(200,215,235,0.85)",
        }}>
          {data.document_count} docs
        </div>
      </div>

      {/* What this collection is / does — grounded collection-level summary */}
      <div style={sectionStyle}>
        <span style={sectionLabel}>What it does</span>
        {loading ? (
          <div style={{ fontSize: 11, color: "rgba(140,200,255,0.6)", fontStyle: "italic" }}>
            loading summary…
          </div>
        ) : error ? (
          <div style={{ fontSize: 11, color: "rgba(140,200,255,0.6)" }}>
            couldn&apos;t load summary
          </div>
        ) : summary ? (
          <div style={{ fontSize: 12, lineHeight: 1.5, color: "rgba(210,222,240,0.9)" }}>
            {summary}
          </div>
        ) : (
          <div style={{ fontSize: 11, color: "rgba(140,200,255,0.6)" }}>
            no summary available
          </div>
        )}
      </div>

      {/* Top Entities */}
      <div style={sectionStyle}>
        <span style={sectionLabel}>Top Entities by Mention</span>
        {loading ? (
          <div style={{ fontSize: 11, color: "rgba(140,200,255,0.6)", fontStyle: "italic" }}>
            loading entities…
          </div>
        ) : error ? (
          // Distinct from the empty case on purpose: an empty list after a FAILED load
          // is not evidence the collection has no entities, and saying so states
          // something the panel does not know.
          <div style={{ fontSize: 11, color: "rgba(140,200,255,0.6)" }}>
            couldn&apos;t load entities
          </div>
        ) : topEntities.length === 0 ? (
          <div style={{ fontSize: 11, color: "rgba(140,200,255,0.6)" }}>
            no entities in this collection
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {topEntities.map((entity) => {
              const barWidth = Math.round((entity.count / maxCount) * 100);
              const entityColor = getEntityColor(entity.type);
              return (
                <button
                  key={entity.id}
                  onClick={() =>
                    onNavigateEntity?.({
                      id: entity.id,
                      name: entity.name,
                      type: entity.type,
                      source_count: entity.count,
                    })
                  }
                  style={{
                    background: "none",
                    border: "none",
                    cursor: onNavigateEntity ? "pointer" : "default",
                    padding: 0,
                    textAlign: "left",
                    fontFamily: "'Courier New', monospace",
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    width: "100%",
                  }}
                >
                  <span style={{
                    fontSize: 10,
                    color: "#e8eaf0",
                    width: 90,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    flexShrink: 0,
                  }}>
                    {entity.name}
                  </span>
                  <div style={{ flex: 1, height: 6, background: "rgba(100,180,255,0.08)", borderRadius: 2, overflow: "hidden" }}>
                    <div
                      style={{
                        height: "100%",
                        width: `${barWidth}%`,
                        background: entityColor,
                        borderRadius: 2,
                      }}
                    />
                  </div>
                  <span style={{ fontSize: 10, color: "rgba(200,215,235,0.85)", width: 28, textAlign: "right", flexShrink: 0 }}>
                    {entity.count}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
