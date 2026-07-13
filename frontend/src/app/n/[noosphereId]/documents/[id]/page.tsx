"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { useNoosphereId } from "@/lib/hooks/use-noosphere-id";
import type { DocumentDetail } from "@/lib/types";

export default function DocumentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const noosphereId = useNoosphereId();
  const id = params.id as string;

  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [fileText, setFileText] = useState<string | null>(null);
  const [fileError, setFileError] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    setDoc(null);
    setFileText(null);
    setFileError(false);
    setError(null);
    api.getDocument(id).then(setDoc).catch((e) => setError(e.message || "Failed to load document"));
  }, [id]);

  useEffect(() => {
    if (!doc || doc.content_type === "image") return;
    api
      .getDocumentFile(id)
      .then(setFileText)
      .catch(() => setFileError(true));
  }, [doc, id]);

  const handleDelete = async () => {
    if (!window.confirm("Delete this document? This cannot be undone.")) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.deleteDocument(id);
      router.push(`/n/${noosphereId}/documents`);
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : "Failed to delete document");
      setDeleting(false);
    }
  };

  if (error) return <div className="p-6 text-red-400 text-sm">{error}</div>;
  if (!doc) return <div className="p-6 text-muted-foreground/80 text-xs animate-pulse">Loading...</div>;

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <button
          onClick={() => router.push(`/n/${noosphereId}/documents`)}
          className="text-[10px] text-muted-foreground/80 hover:text-foreground/90 transition-colors mb-2"
        >
          ← back
        </button>
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold text-foreground/90">{doc.title}</h1>
          <button
            onClick={handleDelete}
            disabled={deleting}
            className="text-[10px] text-destructive/80 hover:text-destructive transition-colors disabled:opacity-50 border border-destructive/30 rounded px-2 py-1"
          >
            {deleting ? "deleting..." : "delete document"}
          </button>
        </div>
        {deleteError && (
          <div className="text-[10px] text-destructive/80 mt-2">{deleteError}</div>
        )}
        <div className="flex items-center gap-3 mt-2">
          <Badge variant="outline" className="text-[10px]">
            {doc.status}
          </Badge>
          <Badge variant="outline" className="text-[10px]">
            {doc.content_type || "text"}
          </Badge>
          <span className="text-xs text-muted-foreground/80">
            {new Date(doc.created_at).toLocaleString()}
          </span>
        </div>
      </div>

      {doc.domains.length > 0 && (
        <div className="border border-border/30 rounded px-4 py-3">
          <div className="text-[9px] tracking-[2px] text-muted-foreground/80 uppercase mb-2">Domains</div>
          <div className="flex gap-2 flex-wrap">
            {doc.domains.map((d) => (
              <Badge key={d.path} variant="outline" className="text-[10px]">
                {d.path} {d.is_primary ? "★" : ""}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {doc.entities.length > 0 && (
        <div className="border border-border/30 rounded px-4 py-3">
          <div className="text-[9px] tracking-[2px] text-muted-foreground/80 uppercase mb-2">
            Entities · {doc.entities.length}
          </div>
          <div className="flex gap-2 flex-wrap">
            {doc.entities.map((e) => (
              <a
                key={e.id}
                href={`/n/${noosphereId}/entities/${e.id}`}
                className="text-[11px] px-2 py-1 rounded border border-border/20 hover:border-border/50 transition-colors text-foreground/80"
              >
                {e.canonical_name}
              </a>
            ))}
          </div>
        </div>
      )}

      <div>
        <div className="text-[9px] tracking-[2px] text-muted-foreground/80 uppercase mb-3">Content</div>
        {doc.content_type === "image" ? (
          <img
            src={`/api/images/${doc.id}`}
            alt={doc.title}
            className="max-w-full rounded border border-border/30"
          />
        ) : (
          <pre className="text-xs text-foreground/85 leading-relaxed whitespace-pre-wrap border border-border/30 rounded p-4 overflow-x-auto max-h-[60vh] overflow-y-auto font-mono">
            {fileText ?? (fileError ? doc.content || "Content unavailable" : "Loading content...")}
          </pre>
        )}
      </div>
    </div>
  );
}
