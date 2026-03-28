"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

// Entity type colors matching cosmic viz exactly
const ENTITY_COLORS: Record<string, string> = {
  Person: "#378ADD",
  Organization: "#7F77DD",
  Product: "#1D9E75",
  Technology: "#BA7517",
  Event: "#D85A30",
  Concept: "#9c9a92",
  Location: "#5DCAA5",
};

function getEntityColor(type: string): string {
  return ENTITY_COLORS[type] ?? "#9c9a92";
}

// Donut SVG for domain weights
function DomainDonut({
  domainWeights,
  domainColors,
}: {
  domainWeights: Record<string, number>;
  domainColors: Record<string, string>;
}) {
  const size = 72;
  const radius = 28;
  const strokeWidth = 10;
  const circumference = 2 * Math.PI * radius;
  const cx = size / 2;
  const cy = size / 2;

  const entries = Object.entries(domainWeights);
  const total = entries.reduce((sum, [, v]) => sum + v, 0);
  if (total === 0 || entries.length === 0) return null;

  const gapFraction = 0.015;
  const gapPerSegment = gapFraction * circumference;
  const totalGap = gapPerSegment * entries.length;
  const usableCircumference = circumference - totalGap;

  // Build arc segments
  let offset = 0; // starts at top (rotated -90deg)
  const segments: { color: string; strokeDasharray: string; strokeDashoffset: number }[] = [];

  for (const [domain, weight] of entries) {
    const fraction = weight / total;
    const arcLength = fraction * usableCircumference;
    const color =
      domainColors[domain] ??
      ENTITY_COLORS[
        ["Person", "Organization", "Product", "Technology", "Event", "Concept", "Location"][
          Math.abs(domain.charCodeAt(0)) % 7
        ]
      ] ??
      "rgba(100,180,255,0.5)";

    segments.push({
      color,
      strokeDasharray: `${arcLength} ${circumference - arcLength}`,
      strokeDashoffset: -(offset),
    });

    offset += arcLength + gapPerSegment;
  }

  return (
    <svg width={size} height={size} style={{ transform: "rotate(-90deg)", flexShrink: 0 }}>
      {/* Track */}
      <circle
        cx={cx}
        cy={cy}
        r={radius}
        fill="none"
        stroke="rgba(100,180,255,0.08)"
        strokeWidth={strokeWidth}
      />
      {segments.map((seg, i) => (
        <circle
          key={i}
          cx={cx}
          cy={cy}
          r={radius}
          fill="none"
          stroke={seg.color}
          strokeWidth={strokeWidth}
          strokeDasharray={seg.strokeDasharray}
          strokeDashoffset={seg.strokeDashoffset}
          strokeLinecap="butt"
        />
      ))}
    </svg>
  );
}

// Highlight entity name in snippet text
function SnippetText({ text, entityName }: { text: string; entityName: string }) {
  if (!entityName) return <span>{text}</span>;

  const lower = text.toLowerCase();
  const nameLower = entityName.toLowerCase();
  const idx = lower.indexOf(nameLower);
  if (idx === -1) return <span>{text}</span>;

  return (
    <span>
      {text.slice(0, idx)}
      <strong style={{ color: "#e8eaf0", fontWeight: 700 }}>{text.slice(idx, idx + entityName.length)}</strong>
      {text.slice(idx + entityName.length)}
    </span>
  );
}

interface CooccurrenceEntity {
  id: string;
  canonical_name: string;
  type: string;
  weight: number;
}

export interface EntityPanelData {
  id: string;
  name: string;
  type: string;
  source_count: number;
  domain_weights?: Record<string, number>;
  snippets?: string[];
}

interface EntityPanelContentProps {
  data: EntityPanelData;
  domainColors: Record<string, string>;
  onNavigateDomain: (domainPath: string, domainName: string) => void;
  onNavigateEntity: (entity: { id: string; name: string; type: string; source_count: number }) => void;
}

export function EntityPanelContent({
  data,
  domainColors,
  onNavigateDomain,
  onNavigateEntity,
}: EntityPanelContentProps) {
  const [mergeHistory, setMergeHistory] = useState<string[]>([]);
  const [cooccurrences, setCooccurrences] = useState<CooccurrenceEntity[]>([]);
  const [snippets, setSnippets] = useState<string[]>(data.snippets ?? []);
  const [loadingSnippets, setLoadingSnippets] = useState(!data.snippets?.length);
  const [loadingCooc, setLoadingCooc] = useState(true);
  const [coocError, setCoocError] = useState(false);
  const [snippetError, setSnippetError] = useState(false);

  const entityColor = getEntityColor(data.type);

  // Fetch entity detail for merge history
  useEffect(() => {
    if (!data.id) return;
    (async () => {
      try {
        const entity = await api.getEntity(data.id);
        setMergeHistory(entity.merge_history ?? []);
      } catch {
        // merge history is optional — silent fail
      }
    })();
  }, [data.id]);

  // Fetch co-occurrences
  useEffect(() => {
    if (!data.id) return;
    setLoadingCooc(true);
    setCoocError(false);
    (async () => {
      try {
        const result = await api.getEntityCooccurrences(data.id);
        setCooccurrences(result.slice(0, 5));
      } catch {
        setCoocError(true);
      } finally {
        setLoadingCooc(false);
      }
    })();
  }, [data.id]);

  // Fetch snippets if not provided in postMessage payload
  useEffect(() => {
    if (data.snippets?.length) {
      setSnippets(data.snippets);
      setLoadingSnippets(false);
      return;
    }
    if (!data.id) {
      setLoadingSnippets(false);
      return;
    }
    setLoadingSnippets(true);
    setSnippetError(false);
    (async () => {
      try {
        // Fetch documents and look for snippets for this entity in the reader endpoint
        const docs = await api.getDocuments();
        const fetchedSnippets: string[] = [];
        for (const doc of docs.slice(0, 10)) {
          if (fetchedSnippets.length >= 2) break;
          try {
            const reader = await api.getDocumentReader(doc.id);
            const entityEntry = reader.entities.find(
              (e) => e.id === data.id || e.canonical_name.toLowerCase() === data.name.toLowerCase()
            );
            if (entityEntry?.snippets?.length) {
              fetchedSnippets.push(...entityEntry.snippets.slice(0, 2 - fetchedSnippets.length));
            }
          } catch {
            // skip doc
          }
        }
        setSnippets(fetchedSnippets.slice(0, 2));
      } catch {
        setSnippetError(true);
      } finally {
        setLoadingSnippets(false);
      }
    })();
  }, [data.id, data.name, data.snippets]);

  const domainWeights = data.domain_weights ?? {};
  const domainEntries = Object.entries(domainWeights).sort(([, a], [, b]) => b - a);
  const totalWeight = domainEntries.reduce((s, [, v]) => s + v, 0);

  const sectionLabel: React.CSSProperties = {
    fontSize: 9,
    color: "rgba(100,180,255,0.4)",
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
        <div style={{ fontSize: 9, color: entityColor, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>
          {data.type}
        </div>
        <div style={{ fontSize: 18, color: "#e8eaf0", lineHeight: 1.2, marginBottom: 4 }}>
          {data.name}
        </div>
        <div style={{ fontSize: 11, color: "rgba(100,180,255,0.4)" }}>
          {data.source_count} docs across corpus
        </div>
      </div>

      {/* Domain Presence */}
      {domainEntries.length > 0 && (
        <div style={sectionStyle}>
          <span style={sectionLabel}>Domain Presence</span>
          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <DomainDonut domainWeights={domainWeights} domainColors={domainColors} />
            <div style={{ flex: 1, minWidth: 0 }}>
              {domainEntries.map(([domain, weight]) => {
                const pct = totalWeight > 0 ? Math.round((weight / totalWeight) * 100) : 0;
                const domainColor = domainColors[domain] ?? "rgba(100,180,255,0.4)";
                const shortName = domain.split("/").pop() ?? domain;
                return (
                  <button
                    key={domain}
                    onClick={() => onNavigateDomain(domain, shortName)}
                    style={{
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                      padding: "2px 0",
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      width: "100%",
                      textAlign: "left",
                      fontFamily: "'Courier New', monospace",
                    }}
                  >
                    <span style={{ fontSize: 10, color: domainColor, minWidth: 0, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {shortName}
                    </span>
                    <span style={{ fontSize: 10, color: "rgba(180,195,220,0.65)", flexShrink: 0 }}>
                      {pct}%
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* From the Docs */}
      <div style={sectionStyle}>
        <span style={sectionLabel}>From the Docs</span>
        {loadingSnippets ? (
          <div style={{ fontSize: 11, color: "rgba(100,180,255,0.4)", fontStyle: "italic" }}>
            loading mentions…
          </div>
        ) : snippetError ? (
          <div style={{ fontSize: 11, color: "rgba(100,180,255,0.4)" }}>
            couldn&apos;t load snippets
          </div>
        ) : snippets.length === 0 ? (
          <div style={{ fontSize: 11, color: "rgba(100,180,255,0.4)" }}>
            no snippets available
          </div>
        ) : (
          snippets.slice(0, 2).map((snippet, i) => (
            <div
              key={i}
              style={{
                marginBottom: i < snippets.length - 1 ? 8 : 0,
                padding: "8px 10px",
                borderLeft: `2px solid ${entityColor}`,
                background: "rgba(100,180,255,0.04)",
                borderRadius: "0 3px 3px 0",
              }}
            >
              <div style={{ fontSize: 11, color: "rgba(180,195,220,0.65)", lineHeight: 1.5 }}>
                &ldquo;<SnippetText text={snippet} entityName={data.name} />&rdquo;
              </div>
            </div>
          ))
        )}
      </div>

      {/* Often Appears With */}
      <div style={sectionStyle}>
        <span style={sectionLabel}>Often Appears With</span>
        {loadingCooc ? (
          <div style={{ fontSize: 11, color: "rgba(100,180,255,0.4)", fontStyle: "italic" }}>
            loading…
          </div>
        ) : coocError ? (
          <div style={{ fontSize: 11, color: "rgba(100,180,255,0.4)" }}>
            couldn&apos;t load co-occurrences
          </div>
        ) : cooccurrences.length === 0 ? (
          <div style={{ fontSize: 11, color: "rgba(100,180,255,0.4)" }}>
            no co-occurrence data
          </div>
        ) : (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {cooccurrences.map((cooc) => {
              const chipColor = getEntityColor(cooc.type);
              return (
                <button
                  key={cooc.id}
                  onClick={() =>
                    onNavigateEntity({
                      id: cooc.id,
                      name: cooc.canonical_name,
                      type: cooc.type,
                      source_count: 0,
                    })
                  }
                  style={{
                    background: "none",
                    border: `1px solid ${chipColor}`,
                    borderRadius: 3,
                    padding: "3px 7px",
                    cursor: "pointer",
                    fontFamily: "'Courier New', monospace",
                    fontSize: 10,
                    color: chipColor,
                  }}
                >
                  {cooc.canonical_name}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Also Known As */}
      {mergeHistory.length > 0 && (
        <div style={sectionStyle}>
          <span style={sectionLabel}>Also Known As</span>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {mergeHistory.map((alias, i) => (
              <span
                key={i}
                style={{
                  fontSize: 11,
                  color: "rgba(100,180,255,0.4)",
                  textDecoration: "line-through",
                  textDecorationColor: "rgba(100,180,255,0.25)",
                }}
              >
                {alias}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Footer */}
      <div style={{ padding: "12px 16px" }}>
        <a
          href={`/entities/${data.id}`}
          style={{
            fontSize: 11,
            color: "rgba(100,180,255,0.7)",
            textDecoration: "none",
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            fontFamily: "'Courier New', monospace",
          }}
        >
          ↗ open entity
        </a>
      </div>
    </div>
  );
}
