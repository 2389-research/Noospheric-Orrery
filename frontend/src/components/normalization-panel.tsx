"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
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

export function NormalizationPanel() {
  const [summary, setSummary] = useState<NormSummary | null>(null);
  const [reviews, setReviews] = useState<ReviewItem[]>([]);
  const [running, setRunning] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const [s, r] = await Promise.all([api.getNormalizationSummary(), api.getReviewQueue()]);
      setSummary(s);
      setReviews(r);
    } catch {
      // endpoints may not exist yet on first load
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleNormalize = async () => {
    setRunning(true);
    setLastResult(null);
    try {
      const result = await api.triggerNormalization();
      setLastResult(
        `${result.plural_merges} plural + ${result.embedding_merges} embedding merges. ` +
        `${result.queued_for_review} queued for review. ` +
        `${result.total_entities_before} → ${result.total_entities_after} entities.`
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

  const methodColors: Record<string, "default" | "secondary" | "outline"> = {
    plural: "outline",
    embedding: "secondary",
    llm_review: "default",
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium">Normalization</h2>
        <Button onClick={handleNormalize} disabled={running}>
          {running ? "Running..." : "Run Normalization"}
        </Button>
      </div>

      {lastResult && (
        <Card className="p-3 text-sm bg-muted">{lastResult}</Card>
      )}

      {summary && summary.total_merges > 0 && (
        <div className="space-y-2">
          <div className="flex gap-4 text-sm">
            {Object.entries(summary.merges_by_method).map(([method, count]) => (
              <span key={method}>
                <Badge variant={methodColors[method] || "outline"}>{method}</Badge> {count}
              </span>
            ))}
            <span className="text-muted-foreground">Total: {summary.total_merges} merges</span>
          </div>

          {summary.recent_merges.length > 0 && (
            <div className="rounded-md border">
              <div className="grid grid-cols-4 gap-4 p-2 border-b font-medium text-xs text-muted-foreground">
                <span>From</span><span>To</span><span>Method</span><span>Similarity</span>
              </div>
              {summary.recent_merges.map((m, i) => (
                <div key={i} className="grid grid-cols-4 gap-4 p-2 border-b last:border-0 text-sm">
                  <span className="line-through text-muted-foreground">{m.from}</span>
                  <span className="font-medium">{m.to}</span>
                  <Badge variant={methodColors[m.method] || "outline"} className="w-fit">{m.method}</Badge>
                  <span className="text-muted-foreground">{m.similarity}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {reviews.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium">Review Queue ({reviews.length} pending)</h3>
          <div className="space-y-2">
            {reviews.map((r) => (
              <Card key={r.id} className="p-3 flex items-center gap-4">
                <span className="font-mono text-sm flex-1">
                  &quot;{r.entity_a}&quot; ↔ &quot;{r.entity_b}&quot;
                </span>
                <span className="text-sm text-muted-foreground">{r.similarity}</span>
                <Button size="sm" variant="default" onClick={() => handleResolve(r.id, "merge")}>
                  Merge
                </Button>
                <Button size="sm" variant="outline" onClick={() => handleResolve(r.id, "keep_separate")}>
                  Keep Separate
                </Button>
              </Card>
            ))}
          </div>
        </div>
      )}

      {summary && summary.total_merges === 0 && reviews.length === 0 && !lastResult && (
        <p className="text-sm text-muted-foreground">No normalization has been run yet. Click &quot;Run Normalization&quot; to deduplicate entities.</p>
      )}
    </div>
  );
}
