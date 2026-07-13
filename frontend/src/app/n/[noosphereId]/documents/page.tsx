"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useNoosphereId } from "@/lib/hooks/use-noosphere-id";
import type { DocumentSummary } from "@/lib/types";

export default function DocumentsPage() {
  const noosphereId = useNoosphereId();
  const router = useRouter();
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const load = () => {
    api.getDocuments().then(setDocuments).catch(console.error);
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (!window.confirm("Delete this document? This cannot be undone.")) return;
    setDeletingId(id);
    setDeleteError(null);
    try {
      await api.deleteDocument(id);
      setDocuments((prev) => prev.filter((d) => d.id !== id));
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Failed to delete document");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-sm tracking-[4px] text-muted-foreground uppercase">Documents</h1>
        <span className="text-xs text-muted-foreground/70">{documents.length} total</span>
      </div>

      {deleteError && <div className="text-[10px] text-destructive/80">{deleteError}</div>}

      <div className="rounded border border-border/30 overflow-hidden">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border/30 text-[9px] tracking-[2px] text-muted-foreground/70 uppercase">
              <th className="text-left px-3 py-2 font-normal">Title</th>
              <th className="text-left px-3 py-2 font-normal">Status</th>
              <th className="text-left px-3 py-2 font-normal">Type</th>
              <th className="text-left px-3 py-2 font-normal">Domains</th>
              <th className="text-left px-3 py-2 font-normal">Entities</th>
              <th className="text-left px-3 py-2 font-normal">Created</th>
              <th className="text-right px-3 py-2 font-normal">Actions</th>
            </tr>
          </thead>
          <tbody>
            {documents.map((doc) => (
              <tr
                key={doc.id}
                onClick={() => router.push(`/n/${noosphereId}/documents/${doc.id}`)}
                className="border-b border-border/10 last:border-0 hover:bg-card/50 transition-colors cursor-pointer"
              >
                <td className="px-3 py-2 text-foreground/90 truncate max-w-xs">{doc.title}</td>
                <td className="px-3 py-2 text-muted-foreground/80">{doc.status}</td>
                <td className="px-3 py-2 text-muted-foreground/80">{doc.content_type || "text"}</td>
                <td className="px-3 py-2 text-muted-foreground/80">
                  <div className="flex gap-1 flex-wrap">
                    {doc.domains.map((d) => (
                      <span key={d} className="px-1.5 py-0.5 rounded border border-border/30 text-[10px]">
                        {d}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-3 py-2 text-muted-foreground/80">{doc.entity_count}</td>
                <td className="px-3 py-2 text-muted-foreground/80">
                  {new Date(doc.created_at).toLocaleDateString()}
                </td>
                <td className="px-3 py-2 text-right">
                  <button
                    onClick={(e) => handleDelete(e, doc.id)}
                    disabled={deletingId === doc.id}
                    className="text-[10px] text-destructive/80 hover:text-destructive transition-colors disabled:opacity-50"
                  >
                    {deletingId === doc.id ? "deleting..." : "delete"}
                  </button>
                </td>
              </tr>
            ))}
            {documents.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-6 text-center text-muted-foreground/70">
                  No documents yet
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
