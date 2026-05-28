"use client";

import Link from "next/link";
import { useNoosphereId } from "@/lib/hooks/use-noosphere-id";

interface NormalizationSummaryProps {
  data: {
    merges_by_method: Record<string, number>;
    total_merges: number;
    pending_reviews: number;
    recent_merges: { from: string; to: string; method: string; similarity: number; date: string }[];
  } | null;
}

const METHOD_LABELS: Record<string, { label: string; sub: string }> = {
  plural:    { label: "Plural collapse",     sub: "entities → entity" },
  embedding: { label: "Embedding similarity", sub: "≥ 0.92 cosine" },
  manual:    { label: "Manual review",       sub: "" },
};

export function NormalizationSummary({ data }: NormalizationSummaryProps) {
  const noosphereId = useNoosphereId();
  if (!data) {
    return (
      <div className="border border-border/30 rounded overflow-hidden">
        <div className="px-4 py-2 border-b border-border/20">
          <span className="text-[9px] tracking-[3px] text-muted-foreground/90 uppercase">Normalization</span>
        </div>
        <div className="p-3">
          <p className="text-[10px] text-muted-foreground/70 animate-pulse">loading…</p>
        </div>
      </div>
    );
  }

  const noMerges = data.total_merges === 0;

  const methods = Object.entries(data.merges_by_method).filter(([, count]) => count > 0);

  return (
    <div className="border border-border/30 rounded overflow-hidden">
      <div className="px-4 py-2 border-b border-border/20">
        <span className="text-[9px] tracking-[3px] text-muted-foreground/90 uppercase">Normalization</span>
      </div>
      <div className="divide-y divide-border/20">
        {noMerges ? (
          <div className="px-4 py-3">
            <p className="text-[10px] text-muted-foreground/70">no merges — all entities distinct</p>
          </div>
        ) : (
          <>
            {methods.map(([method, count]) => {
              const info = METHOD_LABELS[method] ?? { label: method, sub: "" };
              return (
                <div key={method} className="px-4 py-2.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] text-foreground/80">{info.label}</span>
                    <span className="text-[11px] text-muted-foreground/90 font-medium">{count}</span>
                  </div>
                  {info.sub && (
                    <p className="text-[9px] text-muted-foreground/55 mt-0.5">{info.sub}</p>
                  )}
                </div>
              );
            })}
          </>
        )}

        {/* Manual review row */}
        <div className="px-4 py-2.5">
          <div className="flex items-center justify-between">
            <div>
              <span className="text-[11px] text-foreground/80">Manual review</span>
              {data.pending_reviews === 0 ? (
                <p className="text-[9px] text-muted-foreground/70 mt-0.5">0 pending</p>
              ) : (
                <p className="text-[9px] text-amber-400/80 mt-0.5">{data.pending_reviews} pending</p>
              )}
            </div>
            {data.pending_reviews > 0 && (
              <Link
                href={`/n/${noosphereId}/pipeline`}
                className="text-[9px] tracking-[1px] text-cyan-400/80 hover:text-cyan-400 border border-cyan-500/30 rounded px-2 py-0.5 transition-colors"
              >
                review →
              </Link>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
