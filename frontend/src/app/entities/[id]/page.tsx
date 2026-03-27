"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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

export default function EntityDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [entity, setEntity] = useState<EntityDetail | null>(null);
  const [docs, setDocs] = useState<Record<string, DocumentInfo>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/entities/${id}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        return r.json();
      })
      .then(async (e) => {
        setEntity(e);
        // Fetch document titles for sources
        const docIds = [...new Set(e.sources.map((s: { document_id: string }) => s.document_id))];
        const docMap: Record<string, DocumentInfo> = {};
        for (const docId of docIds) {
          try {
            const doc = await fetch(`${API_URL}/documents/${docId}`).then((r) => r.json());
            docMap[docId as string] = doc;
          } catch {
            // skip
          }
        }
        setDocs(docMap);
      })
      .catch((e) => setError(e.message));
  }, [id]);

  if (error) return <div className="p-6 text-destructive">Entity not found</div>;
  if (!entity) return <div className="p-6 text-muted-foreground">Loading...</div>;

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">{entity.canonical_name}</h1>
        <div className="flex gap-2 mt-2">
          <Badge variant="outline">{entity.type}</Badge>
          <span className="text-sm text-muted-foreground">
            {entity.sources.length} source{entity.sources.length !== 1 ? "s" : ""}
          </span>
        </div>
      </div>

      {entity.merge_history.length > 0 && (
        <Card className="p-4">
          <h2 className="text-sm font-medium mb-2">Merge History</h2>
          <p className="text-sm text-muted-foreground">
            Also known as: {entity.merge_history.map((name, i) => (
              <span key={i}>
                {i > 0 && ", "}
                <span className="line-through">{name}</span>
              </span>
            ))}
          </p>
        </Card>
      )}

      <div>
        <h2 className="text-sm font-medium mb-3">Source Documents</h2>
        <div className="space-y-2">
          {[...new Set(entity.sources.map((s) => s.document_id))].map((docId) => {
            const doc = docs[docId];
            const sourcesInDoc = entity.sources.filter((s) => s.document_id === docId);
            return (
              <Card key={docId} className="p-3">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm">{doc?.title || docId}</span>
                  <Badge variant="secondary" className="text-xs">
                    {sourcesInDoc[0]?.extraction_pass || "unknown"}
                  </Badge>
                  <span className="text-xs text-muted-foreground ml-auto">
                    {sourcesInDoc.length} mention{sourcesInDoc.length !== 1 ? "s" : ""}
                  </span>
                </div>
              </Card>
            );
          })}
        </div>
      </div>
    </div>
  );
}
