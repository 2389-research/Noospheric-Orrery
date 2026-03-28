"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

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

function relativeTime(dateStr: string | null | undefined): string {
  if (!dateStr) return "unknown";
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  if (diffSecs < 60) return "just now";
  const diffMins = Math.floor(diffSecs / 60);
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays} day${diffDays !== 1 ? "s" : ""} ago`;
}

interface TopEntity {
  id: string;
  canonical_name: string;
  type: string;
  source_count: number;
}

interface SpecStatus {
  exists: boolean;
  version: number | null;
  simmeredAt: string | null;
  isRunning: boolean;
  jobId?: string;
}

export interface DomainPanelData {
  path: string;
  name: string;
  document_count: number;
}

interface DomainPanelContentProps {
  data: DomainPanelData;
  domainColor?: string;
  onNavigateEntity: (entity: { id: string; name: string; type: string; source_count: number }) => void;
}

export function DomainPanelContent({ data, domainColor, onNavigateEntity }: DomainPanelContentProps) {
  const [topEntities, setTopEntities] = useState<TopEntity[]>([]);
  const [specStatus, setSpecStatus] = useState<SpecStatus>({ exists: false, version: null, simmeredAt: null, isRunning: false });
  const [entityCount, setEntityCount] = useState<number | null>(null);
  const [loadingEntities, setLoadingEntities] = useState(true);
  const [loadingSpec, setLoadingSpec] = useState(true);
  const [entitiesError, setEntitiesError] = useState(false);

  const accentColor = domainColor ?? "rgba(100,180,255,0.8)";
  const shortName = data.path.split("/").pop() ?? data.name;
  const pathParts = data.path.split("/");
  const breadcrumb = pathParts.length > 1 ? pathParts.slice(0, -1).join(" / ") : null;

  // Fetch domain entities
  useEffect(() => {
    setLoadingEntities(true);
    setEntitiesError(false);
    (async () => {
      try {
        const entities = await api.getEntities({ domain: data.path, limit: 50 });
        const sorted = [...entities].sort((a, b) => b.source_count - a.source_count).slice(0, 5);
        setTopEntities(sorted);
        setEntityCount(entities.length);
      } catch {
        setEntitiesError(true);
      } finally {
        setLoadingEntities(false);
      }
    })();
  }, [data.path]);

  // Fetch domain spec status from domains + jobs
  useEffect(() => {
    setLoadingSpec(true);
    (async () => {
      try {
        const [domains, jobs] = await Promise.all([api.getDomains(), api.getJobs()]);
        const domain = domains.find((d) => d.path === data.path);

        // Find latest simmer job for this domain
        const domainJobs = jobs
          .filter((j) => j.type === "simmer_domain" && j.target === data.path)
          .sort((a, b) => {
            const aTime = a.completed_at ?? a.started_at ?? a.created_at;
            const bTime = b.completed_at ?? b.started_at ?? b.created_at;
            return new Date(bTime).getTime() - new Date(aTime).getTime();
          });

        const latestJob = domainJobs[0];
        const isRunning = latestJob?.status === "running" || latestJob?.status === "queued";

        setSpecStatus({
          exists: domain ? (domain.spec_version ?? 0) > 0 : false,
          version: domain?.spec_version ?? null,
          simmeredAt: latestJob?.completed_at ?? latestJob?.started_at ?? null,
          isRunning,
          jobId: latestJob?.id,
        });
      } catch {
        // spec status is informational — silent fail
      } finally {
        setLoadingSpec(false);
      }
    })();
  }, [data.path]);

  const maxCount = topEntities.length > 0 ? topEntities[0].source_count : 1;

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
        <div style={{ fontSize: 9, color: "rgba(100,180,255,0.4)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>
          Domain
        </div>
        <div style={{ fontSize: 18, color: accentColor, lineHeight: 1.2, marginBottom: 4 }}>
          {shortName}
        </div>
        {breadcrumb && (
          <div style={{ fontSize: 11, color: "rgba(100,180,255,0.35)" }}>
            {breadcrumb.replace(/\//g, " / ")}
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
          color: "rgba(180,195,220,0.65)",
        }}>
          {data.document_count} docs
        </div>
        {entityCount !== null && (
          <div style={{
            padding: "4px 8px",
            border: "1px solid rgba(100,180,255,0.15)",
            borderRadius: 3,
            fontSize: 11,
            color: "rgba(180,195,220,0.65)",
          }}>
            {entityCount} entities
          </div>
        )}
      </div>

      {/* Spec status */}
      <div style={sectionStyle}>
        {loadingSpec ? (
          <div style={{ fontSize: 11, color: "rgba(100,180,255,0.4)", fontStyle: "italic" }}>
            checking spec…
          </div>
        ) : specStatus.isRunning ? (
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11 }}>
            <span style={{
              width: 7,
              height: 7,
              borderRadius: "50%",
              background: "#BA7517",
              flexShrink: 0,
              animation: "pulse 1.5s ease-in-out infinite",
            }} />
            <span style={{ color: "rgba(180,195,220,0.65)" }}>
              simmering now…{" "}
              {specStatus.jobId && (
                <a href={`/simmer/${specStatus.jobId}`} style={{ color: "rgba(100,180,255,0.6)", textDecoration: "none" }}>
                  view
                </a>
              )}
            </span>
          </div>
        ) : specStatus.exists ? (
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11 }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#1D9E75", flexShrink: 0 }} />
            <span style={{ color: "rgba(180,195,220,0.65)" }}>
              spec v{specStatus.version}{specStatus.simmeredAt ? ` · simmered ${relativeTime(specStatus.simmeredAt)}` : ""}
            </span>
          </div>
        ) : (
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11 }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", border: "1.5px solid #BA7517", flexShrink: 0 }} />
            <span style={{ color: "rgba(180,195,220,0.65)" }}>no spec · simmer to extract</span>
          </div>
        )}
      </div>

      {/* Top Entities */}
      <div style={sectionStyle}>
        <span style={sectionLabel}>Top Entities by Mention</span>
        {loadingEntities ? (
          <div style={{ fontSize: 11, color: "rgba(100,180,255,0.4)", fontStyle: "italic" }}>
            loading entities…
          </div>
        ) : entitiesError ? (
          <div style={{ fontSize: 11, color: "rgba(100,180,255,0.4)" }}>
            couldn&apos;t load entities
          </div>
        ) : topEntities.length === 0 ? (
          <div style={{ fontSize: 11, color: "rgba(100,180,255,0.4)" }}>
            no entities in this domain
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {topEntities.map((entity) => {
              const barWidth = Math.round((entity.source_count / maxCount) * 100);
              const entityColor = getEntityColor(entity.type);
              return (
                <button
                  key={entity.id}
                  onClick={() =>
                    onNavigateEntity({
                      id: entity.id,
                      name: entity.canonical_name,
                      type: entity.type,
                      source_count: entity.source_count,
                    })
                  }
                  style={{
                    background: "none",
                    border: "none",
                    cursor: "pointer",
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
                    {entity.canonical_name}
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
                  <span style={{ fontSize: 10, color: "rgba(180,195,220,0.65)", width: 20, textAlign: "right", flexShrink: 0 }}>
                    {entity.source_count}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Footer */}
      <div style={{ padding: "12px 16px", display: "flex", gap: 14, alignItems: "center" }}>
        <a
          href={`/documents?domain=${encodeURIComponent(data.path)}`}
          style={{
            fontSize: 11,
            color: "rgba(100,180,255,0.7)",
            textDecoration: "none",
            fontFamily: "'Courier New', monospace",
          }}
        >
          ↗ view docs
        </a>
      </div>
    </div>
  );
}
