"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";

interface NormSummary {
  merges_by_method: Record<string, number>;
  total_merges: number;
  pending_reviews: number;
  recent_merges: { from: string; to: string; method: string; similarity: number; date: string }[];
}

interface ReviewItem {
  id: string;
  entity_a: string;
  entity_b: string;
  similarity: number;
}

const PAGE_SIZE = 6;

const methodStyle: Record<string, string> = {
  plural: "border-yellow-500/40 text-yellow-400",
  embedding: "border-cyan-500/40 text-cyan-400",
  llm_review: "border-purple-500/40 text-purple-400",
};

export function NormalizationPanel() {
  const [summary, setSummary] = useState<NormSummary | null>(null);
  const [reviews, setReviews] = useState<ReviewItem[]>([]);
  const [running, setRunning] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);
  const [mergePage, setMergePage] = useState(0);
  const [reviewPage, setReviewPage] = useState(0);

  const refresh = async () => {
    try {
      const [s, r] = await Promise.all([api.getNormalizationSummary(), api.getReviewQueue()]);
      setSummary(s);
      setReviews(r);
    } catch { /* endpoints may not exist yet */ }
  };

  useEffect(() => { refresh(); }, []);

  const handleNormalize = async () => {
    setRunning(true);
    setLastResult(null);
    try {
      const result = await api.triggerNormalization();
      setLastResult(
        `${result.plural_merges} plural + ${result.embedding_merges} embedding → ` +
        `${result.total_entities_before} → ${result.total_entities_after} entities. ` +
        `${result.queued_for_review} queued.`
      );
      refresh();
    } catch (e) {
      setLastResult(`Error: ${e}`);
    }
    setRunning(false);
  };

  const handleResolve = async (id: string, action: "merge" | "keep_separate") => {
    await api.resolveReview(id, action);
    refresh();
  };

  const merges = summary?.recent_merges || [];
  const mergeTotalPages = Math.ceil(merges.length / PAGE_SIZE);
  const visibleMerges = merges.slice(mergePage * PAGE_SIZE, (mergePage + 1) * PAGE_SIZE);

  const reviewTotalPages = Math.ceil(reviews.length / PAGE_SIZE);
  const visibleReviews = reviews.slice(reviewPage * PAGE_SIZE, (reviewPage + 1) * PAGE_SIZE);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h2 className="text-xs tracking-[3px] text-muted-foreground uppercase">Normalization</h2>
          {summary && summary.total_merges > 0 && (
            <div className="flex gap-3 text-[10px]">
              {Object.entries(summary.merges_by_method).map(([method, count]) => (
                <span key={method} className="flex items-center gap-1">
                  <Badge variant="outline" className={`text-[9px] ${methodStyle[method] || ""}`}>{method}</Badge>
                  <span className="text-muted-foreground/50">{count}</span>
                </span>
              ))}
            </div>
          )}
        </div>
        <Button size="sm" variant="outline" className="text-xs tracking-wider" onClick={handleNormalize} disabled={running}>
          {running ? "running..." : "Normalize"}
        </Button>
      </div>

      {lastResult && (
        <div className="border border-border/30 rounded px-3 py-2 text-[10px] text-muted-foreground/70">{lastResult}</div>
      )}

      {visibleMerges.length > 0 && (
        <div className="space-y-2">
          <div className="rounded border border-border/30">
            <div className="grid grid-cols-[1fr_1fr_80px_60px] gap-2 px-3 py-1.5 border-b border-border/20 text-[9px] tracking-[2px] text-muted-foreground/50 uppercase">
              <span>From</span><span>To</span><span>Method</span><span>Sim</span>
            </div>
            {visibleMerges.map((m, i) => (
              <div key={i} className="grid grid-cols-[1fr_1fr_80px_60px] gap-2 px-3 py-1.5 border-b border-border/10 last:border-0 text-xs">
                <span className="line-through text-muted-foreground/40">{m.from}</span>
                <span className="text-foreground/80">{m.to}</span>
                <Badge variant="outline" className={`w-fit text-[9px] ${methodStyle[m.method] || ""}`}>{m.method}</Badge>
                <span className="text-muted-foreground/50">{m.similarity}</span>
              </div>
            ))}
          </div>
          {mergeTotalPages > 1 && (
            <div className="flex items-center justify-end gap-1 text-xs text-muted-foreground/50">
              <Button size="sm" variant="ghost" className="h-5 text-[10px] px-2" disabled={mergePage === 0} onClick={() => setMergePage(p => p - 1)}>←</Button>
              <span className="px-2">{mergePage + 1}/{mergeTotalPages}</span>
              <Button size="sm" variant="ghost" className="h-5 text-[10px] px-2" disabled={mergePage >= mergeTotalPages - 1} onClick={() => setMergePage(p => p + 1)}>→</Button>
            </div>
          )}
        </div>
      )}

      {visibleReviews.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-[10px] tracking-[2px] text-muted-foreground/50 uppercase">
            Review Queue · {reviews.length} pending
          </h3>
          <div className="space-y-1">
            {visibleReviews.map((r) => (
              <div key={r.id} className="flex items-center gap-3 border border-border/20 rounded px-3 py-2">
                <span className="text-xs text-foreground/70 flex-1">
                  &quot;{r.entity_a}&quot; <span className="text-muted-foreground/50">↔</span> &quot;{r.entity_b}&quot;
                </span>
                <span className="text-[10px] text-muted-foreground/40">{r.similarity}</span>
                <Button size="sm" variant="outline" className="h-5 text-[10px] px-2 border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10" onClick={() => handleResolve(r.id, "merge")}>
                  merge
                </Button>
                <Button size="sm" variant="ghost" className="h-5 text-[10px] px-2 text-muted-foreground/50" onClick={() => handleResolve(r.id, "keep_separate")}>
                  skip
                </Button>
              </div>
            ))}
          </div>
          {reviewTotalPages > 1 && (
            <div className="flex items-center justify-end gap-1 text-xs text-muted-foreground/50">
              <Button size="sm" variant="ghost" className="h-5 text-[10px] px-2" disabled={reviewPage === 0} onClick={() => setReviewPage(p => p - 1)}>←</Button>
              <span className="px-2">{reviewPage + 1}/{reviewTotalPages}</span>
              <Button size="sm" variant="ghost" className="h-5 text-[10px] px-2" disabled={reviewPage >= reviewTotalPages - 1} onClick={() => setReviewPage(p => p + 1)}>→</Button>
            </div>
          )}
        </div>
      )}

      {(!summary || summary.total_merges === 0) && reviews.length === 0 && !lastResult && (
        <p className="text-[10px] text-muted-foreground/40">No normalization run yet.</p>
      )}
    </div>
  );
}
