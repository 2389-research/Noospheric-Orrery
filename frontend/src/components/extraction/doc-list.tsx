"use client";

import type { DocumentSummary } from "@/lib/types";

interface DocListProps {
  docs: DocumentSummary[];
  selectedDocId: string | null;
  onSelectDoc: (id: string | null) => void;
  isRunning: boolean;
}

export function DocList({ docs, selectedDocId, onSelectDoc, isRunning }: DocListProps) {
  const sorted = [...docs].sort((a, b) => b.entity_count - a.entity_count);
  const maxCount = sorted.length > 0 ? Math.max(...sorted.map((d) => d.entity_count)) : 1;

  return (
    <div className="flex flex-col h-full border border-border/30 rounded overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border/20 shrink-0">
        <span className="text-[9px] tracking-[3px] text-muted-foreground/90 uppercase">Documents</span>
        <span className="text-[10px] text-muted-foreground/70">{docs.length} docs</span>
      </div>

      {/* Doc rows */}
      <div className="overflow-y-auto flex-1">
        {sorted.map((doc) => {
          const isActive = doc.id === selectedDocId;
          const isPending = doc.status === "classified" && isRunning;
          const barWidth = maxCount > 0 ? (doc.entity_count / maxCount) * 100 : 0;

          return (
            <button
              key={doc.id}
              className={`w-full text-left px-3 py-2 border-b border-border/10 transition-colors hover:bg-card/40 focus:outline-none ${
                isActive ? "border-l-2 border-l-cyan-400 bg-cyan-500/5" : "border-l-2 border-l-transparent"
              } ${isPending ? "opacity-50" : ""}`}
              onClick={() => onSelectDoc(isActive ? null : doc.id)}
            >
              <div className="flex items-start justify-between gap-1 mb-0.5">
                <span className="text-[11px] text-foreground/90 truncate leading-tight">
                  {doc.title}
                </span>
              </div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-[9px] text-muted-foreground/70 truncate max-w-[120px]">
                  {doc.domains[0] ?? "—"}
                </span>
                <span className="text-[9px] text-muted-foreground/80 shrink-0 ml-1">
                  {isPending ? (
                    <span className="flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-amber-400/70 animate-pulse" />
                      —
                    </span>
                  ) : (
                    doc.entity_count
                  )}
                </span>
              </div>
              {/* Bar */}
              <div className="h-[2px] bg-border/20 rounded overflow-hidden">
                {!isPending && (
                  <div
                    className="h-full bg-cyan-500/50 rounded transition-all duration-300"
                    style={{ width: `${barWidth}%` }}
                  />
                )}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
