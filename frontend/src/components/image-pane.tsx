"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface ImagePaneProps {
  documentId: string;
  onClose: () => void;
  onNavigateEntity?: (entityId: string) => void;
}

interface ImageDocDetail {
  id: string;
  title: string;
  content: string; // description
  domains: { domain_path: string }[];
  entities: { id: string; canonical_name: string; type: string }[];
  image_path?: string;
  thumbnail_path?: string;
}

export function ImagePane({ documentId, onClose, onNavigateEntity }: ImagePaneProps) {
  const [doc, setDoc] = useState<ImageDocDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const detail = await api.getDocument(documentId);
        setDoc(detail as unknown as ImageDocDetail);
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

  return (
    <div style={{ fontFamily: "'Courier New', monospace", height: "100%", display: "flex", flexDirection: "column" }}>
      {/* Header */}
      <div style={{ padding: "12px 16px", borderBottom: "1px solid rgba(100,200,180,0.12)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <div style={{ fontSize: 9, color: "rgba(100,200,180,0.7)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 2 }}>
            Image Document
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

      {/* Image */}
      <div style={{ padding: 16, borderBottom: "1px solid rgba(100,200,180,0.08)" }}>
        {doc.thumbnail_path ? (
          <img
            src={`/api/files/${encodeURIComponent(doc.thumbnail_path)}`}
            alt={doc.title}
            style={{ width: "100%", borderRadius: 4, border: "1px solid rgba(100,200,180,0.15)" }}
          />
        ) : (
          <div style={{ width: "100%", height: 200, background: "rgba(100,200,180,0.08)", borderRadius: 4, display: "flex", alignItems: "center", justifyContent: "center", color: "rgba(140,200,255,0.4)", fontSize: 32 }}>
            📷
          </div>
        )}
      </div>

      {/* Description */}
      <div style={{ padding: "12px 16px", borderBottom: "1px solid rgba(100,200,180,0.08)" }}>
        <div style={{ fontSize: 9, color: "rgba(140,200,255,0.6)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>
          Description
        </div>
        <div style={{ fontSize: 11, color: "rgba(200,215,235,0.85)", lineHeight: 1.6 }}>
          {doc.content || "No description available."}
        </div>
      </div>

      {/* Domains */}
      {doc.domains && doc.domains.length > 0 && (
        <div style={{ padding: "12px 16px", borderBottom: "1px solid rgba(100,200,180,0.08)" }}>
          <div style={{ fontSize: 9, color: "rgba(140,200,255,0.6)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>
            Domains
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {doc.domains.map((d) => (
              <span key={d.domain_path} style={{ fontSize: 10, color: "rgba(100,200,180,0.8)", padding: "2px 6px", border: "1px solid rgba(100,200,180,0.2)", borderRadius: 3 }}>
                {d.domain_path}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Entities */}
      {doc.entities && doc.entities.length > 0 && (
        <div style={{ padding: "12px 16px", flex: 1, overflowY: "auto" }}>
          <div style={{ fontSize: 9, color: "rgba(140,200,255,0.6)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>
            Entities · {doc.entities.length}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {doc.entities.map((e) => (
              <button
                key={e.id}
                onClick={() => onNavigateEntity?.(e.id)}
                style={{
                  background: "none", border: "1px solid rgba(100,180,255,0.2)", borderRadius: 3,
                  padding: "3px 7px", cursor: "pointer", fontFamily: "'Courier New', monospace",
                  fontSize: 10, color: "rgba(200,215,235,0.85)",
                }}
              >
                {e.canonical_name}
                <span style={{ color: "rgba(140,200,255,0.4)", marginLeft: 4, fontSize: 9 }}>{e.type}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
