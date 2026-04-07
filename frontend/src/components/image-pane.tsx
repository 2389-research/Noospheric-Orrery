"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useNoosphereId } from "@/lib/hooks/use-noosphere-id";

interface ImagePaneProps {
  documentId: string;
  onClose: () => void;
  onNavigateEntity?: (entityId: string) => void;
}

interface ImageEntity {
  id: string;
  canonical_name: string;
  type: string;
  source_count: number;
}

interface ImageDocDetail {
  id: string;
  title: string;
  description: string;
  domains: string[];
  entities: ImageEntity[];
}

const ENTITY_COLORS: Record<string, string> = {
  Subject: "#378ADD",
  Object: "#7F77DD",
  Person: "#1D9E75",
  Setting: "#BA7517",
  Material: "#D85A30",
  Color: "#5DCAA5",
  Text: "#9c9a92",
};

function getColor(type: string): string {
  return ENTITY_COLORS[type] ?? "#9c9a92";
}

export function ImagePane({ documentId, onClose, onNavigateEntity }: ImagePaneProps) {
  const noosphereId = useNoosphereId();
  const [doc, setDoc] = useState<ImageDocDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [imageError, setImageError] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const reader = await api.getDocumentReader(documentId);
        const d = reader.document;
        const description = reader.segments
          ?.filter((s: { type: string }) => s.type === "text")
          .map((s: { text: string }) => s.text)
          .join(" ") || "";
        setDoc({
          id: d.id,
          title: d.title,
          description,
          domains: d.domains || [],
          entities: reader.entities || [],
        });
      } catch {
        // fallback
      } finally {
        setLoading(false);
      }
    })();
  }, [documentId]);

  if (loading) {
    return (
      <div style={{ padding: 20, color: "rgba(140,200,255,0.6)", fontFamily: "'Courier New', monospace", fontSize: 11 }}>
        loading image…
      </div>
    );
  }

  if (!doc) {
    return (
      <div style={{ padding: 20, color: "rgba(140,200,255,0.6)", fontFamily: "'Courier New', monospace", fontSize: 11 }}>
        document not found
      </div>
    );
  }

  const imageUrl = `/api/images/${documentId}`;

  // Group entities by type
  const entityGroups: Record<string, ImageEntity[]> = {};
  for (const e of doc.entities) {
    const t = e.type || "Other";
    if (!entityGroups[t]) entityGroups[t] = [];
    entityGroups[t].push(e);
  }

  return (
    <div style={{ fontFamily: "'Courier New', monospace", height: "100%", display: "flex", flexDirection: "column" }}>
      {/* Header */}
      <div style={{ padding: "12px 16px", borderBottom: "1px solid rgba(100,200,180,0.12)", display: "flex", justifyContent: "space-between", alignItems: "center", flexShrink: 0 }}>
        <div>
          <div style={{ fontSize: 9, color: "rgba(100,200,180,0.7)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 2 }}>
            Image
          </div>
          <div style={{ fontSize: 13, color: "#e8eaf0" }}>{doc.title}</div>
        </div>
        <button
          onClick={onClose}
          style={{ background: "none", border: "none", cursor: "pointer", color: "rgba(100,180,255,0.35)", fontSize: 14, fontFamily: "'Courier New', monospace" }}
        >
          ✕
        </button>
      </div>

      <div style={{ flex: 1, overflowY: "auto" }}>
        {/* Image — the main artifact */}
        <div style={{ padding: 12, borderBottom: "1px solid rgba(100,200,180,0.08)" }}>
          {!imageError ? (
            <img
              src={imageUrl}
              alt={doc.title}
              onError={() => setImageError(true)}
              style={{ width: "100%", borderRadius: 4, border: "1px solid rgba(100,200,180,0.15)", display: "block" }}
            />
          ) : (
            <div style={{ width: "100%", height: 200, background: "rgba(100,200,180,0.08)", borderRadius: 4, display: "flex", alignItems: "center", justifyContent: "center", color: "rgba(140,200,255,0.3)", fontSize: 11 }}>
              image not available in this container
            </div>
          )}
        </div>

        {/* Domains */}
        {doc.domains.length > 0 && (
          <div style={{ padding: "10px 16px", borderBottom: "1px solid rgba(100,200,180,0.08)" }}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {doc.domains.map((dp) => (
                <span key={dp} style={{ fontSize: 9, color: "rgba(100,200,180,0.8)", padding: "2px 6px", border: "1px solid rgba(100,200,180,0.2)", borderRadius: 3 }}>
                  {dp.split("/").pop()}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Entities — grouped by type, clickable for navigation */}
        {doc.entities.length > 0 && (
          <div style={{ padding: "12px 16px", borderBottom: "1px solid rgba(100,200,180,0.08)" }}>
            <div style={{ fontSize: 9, color: "rgba(140,200,255,0.6)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>
              Entities · {doc.entities.length}
            </div>
            {Object.entries(entityGroups).map(([type, entities]) => (
              <div key={type} style={{ marginBottom: 8 }}>
                <div style={{ fontSize: 9, color: getColor(type), textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
                  {type}
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {entities.map((e) => (
                    <button
                      key={e.id}
                      onClick={() => onNavigateEntity?.(e.id)}
                      style={{
                        background: "none",
                        border: `1px solid ${getColor(type)}`,
                        borderRadius: 3,
                        padding: "3px 7px",
                        cursor: "pointer",
                        fontFamily: "'Courier New', monospace",
                        fontSize: 10,
                        color: getColor(type),
                        transition: "background 0.15s",
                      }}
                      onMouseEnter={(ev) => { ev.currentTarget.style.background = "rgba(100,180,255,0.1)"; }}
                      onMouseLeave={(ev) => { ev.currentTarget.style.background = "none"; }}
                    >
                      {e.canonical_name}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Description */}
        <div style={{ padding: "12px 16px" }}>
          <div style={{ fontSize: 9, color: "rgba(140,200,255,0.6)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>
            Description
          </div>
          <div style={{ fontSize: 11, color: "rgba(200,215,235,0.75)", lineHeight: 1.6 }}>
            {doc.description || "No description available."}
          </div>
        </div>
      </div>
    </div>
  );
}
