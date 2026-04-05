"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { useNoosphereId } from "@/lib/hooks/use-noosphere-id";
import { getAuthToken } from "@/lib/firebase";

const TYPE_COLORS: Record<string, string> = {
  Person: "#378ADD",
  Organization: "#7F77DD",
  Product: "#1D9E75",
  Technology: "#BA7517",
  Event: "#D85A30",
  Concept: "#9c9a92",
  Location: "#5DCAA5",
};

interface EntityDetail {
  id: string;
  canonical_name: string;
  type: string;
  created_at: string;
  sources: { document_id: string; chunk_id: string; extraction_pass: string; spec_version: number | null }[];
  merge_history: string[];
}

interface DocumentInfo {
  id: string;
  title: string;
  status: string;
}

interface DocSnippets {
  snippets: string[];
  loading: boolean;
}

export default function EntityDetailPage() {
  const params = useParams();
  const router = useRouter();
  const noosphereId = useNoosphereId();
  const id = params.id as string;
  const [entity, setEntity] = useState<EntityDetail | null>(null);
  const [docs, setDocs] = useState<Record<string, DocumentInfo>>({});
  const [expandedDoc, setExpandedDoc] = useState<string | null>(null);
  const [docSnippets, setDocSnippets] = useState<Record<string, DocSnippets>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const token = await getAuthToken();
        const headers: Record<string, string> = {};
        if (token) headers["Authorization"] = `Bearer ${token}`;
        if (noosphereId) headers["X-Workspace-Id"] = noosphereId;

        const r = await fetch(`/api/entities/${id}`, { headers });
        if (!r.ok) throw new Error(`${r.status}`);
        const e = await r.json();
        setEntity(e);
        const docIds = [...new Set(e.sources.map((s: { document_id: string }) => s.document_id))];
        const docMap: Record<string, DocumentInfo> = {};
        for (const docId of docIds) {
          try {
            const doc = await fetch(`/api/documents/${docId}`, { headers }).then((r) => r.json());
            docMap[docId as string] = doc;
          } catch {
            // skip
          }
        }
        setDocs(docMap);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load entity");
      }
    })();
  }, [id, noosphereId]);

  const handleToggleDoc = async (docId: string) => {
    if (expandedDoc === docId) {
      setExpandedDoc(null);
      return;
    }
    setExpandedDoc(docId);

    if (!docSnippets[docId]) {
      setDocSnippets((prev) => ({ ...prev, [docId]: { snippets: [], loading: true } }));
      try {
        const token = await getAuthToken();
        const headers: Record<string, string> = {};
        if (token) headers["Authorization"] = `Bearer ${token}`;
        if (noosphereId) headers["X-Workspace-Id"] = noosphereId;
        const reader = await fetch(`/api/documents/${docId}/reader`, { headers }).then((r) => r.json());
        const entityData = reader.entities?.find(
          (e: { id: string; canonical_name: string }) =>
            e.id === id || e.canonical_name === entity?.canonical_name
        );
        const snippets = entityData?.snippets || [];

        if (snippets.length === 0 && reader.segments) {
          const foundSnippets: string[] = [];
          const segments = reader.segments as { type: string; text: string; entity_id?: string }[];
          for (let i = 0; i < segments.length; i++) {
            if (segments[i].entity_id === id || segments[i].entity_id === entity?.canonical_name) {
              const before = segments.slice(Math.max(0, i - 2), i).map((s) => s.text).join("");
              const match = segments[i].text;
              const after = segments.slice(i + 1, Math.min(segments.length, i + 3)).map((s) => s.text).join("");
              foundSnippets.push(before + match + after);
            }
          }
          setDocSnippets((prev) => ({ ...prev, [docId]: { snippets: foundSnippets.slice(0, 5), loading: false } }));
        } else {
          setDocSnippets((prev) => ({ ...prev, [docId]: { snippets, loading: false } }));
        }
      } catch {
        setDocSnippets((prev) => ({ ...prev, [docId]: { snippets: [], loading: false } }));
      }
    }
  };

  if (error) return <div className="p-6 text-red-400 text-sm">Entity not found</div>;
  if (!entity) return <div className="p-6 text-muted-foreground/80 text-xs animate-pulse">Loading...</div>;

  const typeColor = TYPE_COLORS[entity.type] || "#9c9a92";
  const docIds = [...new Set(entity.sources.map((s) => s.document_id))];

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <button
          onClick={() => router.push(`/n/${noosphereId}/entities`)}
          className="text-[10px] text-muted-foreground/80 hover:text-foreground/90 transition-colors mb-2"
        >
          ← back
        </button>
        <h1 className="text-xl font-semibold text-foreground/90">{entity.canonical_name}</h1>
        <div className="flex items-center gap-3 mt-2">
          <Badge variant="outline" className="text-[10px]" style={{ borderColor: `${typeColor}60`, color: typeColor }}>
            {entity.type}
          </Badge>
          <span className="text-xs text-muted-foreground/80">
            {entity.sources.length} mention{entity.sources.length !== 1 ? "s" : ""} across {docIds.length} doc{docIds.length !== 1 ? "s" : ""}
          </span>
        </div>
      </div>

      {entity.merge_history.length > 0 && (
        <div className="border border-border/30 rounded px-4 py-3">
          <div className="text-[9px] tracking-[2px] text-muted-foreground/80 uppercase mb-1">Merge History</div>
          <p className="text-xs text-muted-foreground/80">
            Also known as: {entity.merge_history.map((name, i) => (
              <span key={i}>
                {i > 0 && ", "}
                <span className="line-through text-muted-foreground/80">{name}</span>
              </span>
            ))}
          </p>
        </div>
      )}

      <div>
        <div className="text-[9px] tracking-[2px] text-muted-foreground/80 uppercase mb-3">
          Source Documents · {docIds.length}
        </div>
        <div className="space-y-1">
          {docIds.map((docId) => {
            const doc = docs[docId];
            const sourcesInDoc = entity.sources.filter((s) => s.document_id === docId);
            const isExpanded = expandedDoc === docId;
            const snippetData = docSnippets[docId];

            return (
              <div key={docId} className="border border-border/30 rounded overflow-hidden">
                <button
                  onClick={() => handleToggleDoc(docId)}
                  className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-card/50 transition-colors text-left"
                >
                  <span className="w-1 h-6 rounded-full shrink-0" style={{ backgroundColor: isExpanded ? typeColor : "transparent" }} />
                  <span className="text-xs text-foreground/90 flex-1 truncate">{doc?.title || docId}</span>
                  <Badge variant="outline" className="text-[9px] border-border/30 text-muted-foreground/80">
                    {sourcesInDoc[0]?.extraction_pass || "unknown"}
                  </Badge>
                  <span className="text-[10px] text-muted-foreground/80 w-16 text-right">
                    {sourcesInDoc.length} mention{sourcesInDoc.length !== 1 ? "s" : ""}
                  </span>
                  <span className="text-muted-foreground/80 text-xs">{isExpanded ? "▲" : "▼"}</span>
                </button>

                {isExpanded && (
                  <div className="px-4 pb-3 border-t border-border/20">
                    {snippetData?.loading && (
                      <div className="text-[10px] text-muted-foreground/80 py-3 animate-pulse">loading context...</div>
                    )}
                    {snippetData && !snippetData.loading && snippetData.snippets.length === 0 && (
                      <div className="text-[10px] text-muted-foreground/80 py-3">No context snippets available</div>
                    )}
                    {snippetData && !snippetData.loading && snippetData.snippets.map((snippet, i) => (
                      <div key={i} className="py-2 border-b border-border/10 last:border-0">
                        <HighlightedSnippet text={snippet} entityName={entity.canonical_name} mergeHistory={entity.merge_history} color={typeColor} />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function HighlightedSnippet({ text, entityName, mergeHistory, color }: { text: string; entityName: string; mergeHistory: string[]; color: string }) {
  const names = [entityName, ...mergeHistory].filter(Boolean);
  const pattern = names.map((n) => `(?<!\\w)${n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?!\\w)`).join("|");

  let regex: RegExp;
  try {
    regex = new RegExp(`(${pattern})`, "gi");
  } catch {
    return <span className="text-xs text-foreground/85 leading-relaxed">{text}</span>;
  }

  const parts = text.split(regex);

  return (
    <span className="text-xs text-foreground/85 leading-relaxed">
      {parts.map((part, i) => {
        const isMatch = names.some((n) => part.toLowerCase() === n.toLowerCase());
        if (isMatch) {
          return (
            <span key={i} style={{ color: "#ffffff", background: `${color}40`, borderBottom: `1.5px solid ${color}`, borderRadius: "2px", padding: "0 2px" }}>
              {part}
            </span>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </span>
  );
}
