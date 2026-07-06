"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import type { Correction, CorrectionAction, JudgeVerdict } from "@/lib/types";

const actionStyle: Record<CorrectionAction, string> = {
  invalidate: "border-rose-500/40 text-rose-400",
  merge: "border-cyan-500/40 text-cyan-400",
  retype: "border-purple-500/40 text-purple-400",
  rename: "border-amber-500/40 text-amber-400",
};

const verdictStyle: Record<JudgeVerdict, string> = {
  accept: "border-emerald-500/40 text-emerald-400",
  reject: "border-rose-500/40 text-rose-400",
  defer: "border-amber-500/40 text-amber-400",
};

// Surface the actionable proposals: accepts first (highest confidence), then defers,
// then rejects, then not-yet-judged.
const verdictRank: Record<string, number> = { accept: 0, defer: 1, reject: 2 };
function sortCorrections(a: Correction, b: Correction): number {
  const ra = a.judge_verdict ? verdictRank[a.judge_verdict] : 3;
  const rb = b.judge_verdict ? verdictRank[b.judge_verdict] : 3;
  if (ra !== rb) return ra - rb;
  return (b.judge_confidence ?? 0) - (a.judge_confidence ?? 0);
}

// The proposed change, phrased per action.
function changeLabel(c: Correction): string {
  if (c.action === "merge") return `merge with "${c.target_b_name ?? "?"}"`;
  if (c.action === "retype") return `retype → ${c.proposed_type ?? "?"}`;
  if (c.action === "rename") return `rename → "${c.proposed_name ?? "?"}"`;
  return "invalidate (not a real entity)";
}

export function CorrectionsPanel() {
  const [items, setItems] = useState<Correction[]>([]);
  const [judging, setJudging] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setItems(await api.getCorrections());
    } catch {
      /* endpoint may not exist yet */
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 15000); // verdicts land after the judge sweep/job runs
    return () => clearInterval(t);
  }, [refresh]);

  const handleJudge = async () => {
    setJudging(true);
    setNote(null);
    try {
      await api.triggerJudgeCorrections();
      setNote("Judge queued — verdicts will appear shortly.");
      setTimeout(refresh, 3000);
    } catch (e) {
      setNote(`Error: ${e}`);
    }
    setJudging(false);
  };

  const handleResolve = async (id: string, action: "approve" | "reject") => {
    await api.resolveCorrection(id, action);
    refresh();
  };

  const sorted = [...items].sort(sortCorrections);
  const unjudged = items.filter((c) => !c.judge_verdict).length;

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h2 className="text-xs tracking-[3px] text-muted-foreground uppercase">Graph Corrections</h2>
          {items.length > 0 && (
            <span className="text-[10px] text-muted-foreground/85">
              {items.length} pending{unjudged > 0 ? ` · ${unjudged} awaiting judge` : ""}
            </span>
          )}
        </div>
        <Button
          size="sm"
          variant="outline"
          className="text-xs tracking-wider"
          onClick={handleJudge}
          disabled={judging || unjudged === 0}
        >
          {judging ? "queuing..." : "judge pending"}
        </Button>
      </div>

      {note && (
        <div className="border border-border/30 rounded px-3 py-2 text-[10px] text-muted-foreground/85">{note}</div>
      )}

      {sorted.length > 0 ? (
        <div className="space-y-1.5">
          {sorted.map((c) => (
            <div key={c.id} className="border border-border/20 rounded px-3 py-2 space-y-1.5">
              <div className="flex items-center gap-2">
                <Badge variant="outline" className={`text-[9px] ${actionStyle[c.action] ?? ""}`}>{c.action}</Badge>
                <span className="text-xs text-foreground/90">&quot;{c.target_entity_name}&quot;</span>
                <span className="text-[10px] text-muted-foreground/70">{changeLabel(c)}</span>
                <span className="ml-auto text-[9px] text-muted-foreground/60">by {c.proposer ?? "unknown"}</span>
              </div>

              {c.rationale && (
                <p className="text-[10px] text-muted-foreground/85 leading-relaxed">{c.rationale}</p>
              )}

              {c.judge_verdict ? (
                <div className="flex items-start gap-2 border-t border-border/10 pt-1.5">
                  <Badge variant="outline" className={`text-[9px] ${verdictStyle[c.judge_verdict] ?? ""}`}>
                    judge: {c.judge_verdict}
                  </Badge>
                  {c.judge_confidence != null && (
                    <span className="text-[9px] text-muted-foreground/70 pt-0.5">conf {c.judge_confidence.toFixed(2)}</span>
                  )}
                  {c.judge_rationale && (
                    <p className="text-[10px] text-muted-foreground/75 leading-relaxed flex-1">{c.judge_rationale}</p>
                  )}
                </div>
              ) : (
                <div className="border-t border-border/10 pt-1.5">
                  <span className="text-[9px] text-muted-foreground/55 italic">awaiting judge</span>
                </div>
              )}

              <div className="flex items-center gap-2 border-t border-border/10 pt-1.5">
                {c.action === "merge" && (
                  <span className="text-[9px] text-muted-foreground/50 italic mr-auto">merge apply deferred — approve records the decision</span>
                )}
                <Button size="sm" variant="outline"
                  className="h-5 text-[10px] px-2 border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10 ml-auto"
                  onClick={() => handleResolve(c.id, "approve")}>approve</Button>
                <Button size="sm" variant="ghost"
                  className="h-5 text-[10px] px-2 text-muted-foreground/85"
                  onClick={() => handleResolve(c.id, "reject")}>reject</Button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-[10px] text-muted-foreground/90">No pending corrections. Agents file these via the propose_correction tool.</p>
      )}
    </section>
  );
}
