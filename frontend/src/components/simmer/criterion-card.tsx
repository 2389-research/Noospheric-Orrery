"use client";

import { useState } from "react";
import { CriterionDetail, SimmerIteration } from "@/lib/types";

const CRITERION_COLORS = ["#378ADD", "#BA7517", "#1D9E75", "#9B5E8A", "#6B7280"];

interface CriterionCardProps {
  detail: CriterionDetail;
  colorIndex: number;
  nextIteration?: SimmerIteration;
}

export function CriterionCard({ detail, colorIndex, nextIteration }: CriterionCardProps) {
  const [expanded, setExpanded] = useState(false);
  const color = CRITERION_COLORS[colorIndex % CRITERION_COLORS.length];
  const barWidth = Math.max(0, Math.min(100, (detail.score / 10) * 100));
  const seedDelta = detail.score - detail.seed_score;

  // Check if next iteration acted on this criterion
  const nextActed =
    nextIteration &&
    nextIteration.criterion_details.some((d) => d.criterion === detail.criterion);

  return (
    <div className="border border-border/20 rounded overflow-hidden">
      {/* Collapsed header */}
      <button
        onClick={() => setExpanded((e) => !e)}
        className="w-full flex items-center gap-3 px-3 py-2 hover:bg-card/50 transition-colors text-left"
      >
        <span
          className="text-[10px] tracking-[1px] uppercase font-semibold w-28 shrink-0"
          style={{ color }}
        >
          {detail.criterion}
        </span>
        <div className="flex-1 h-1.5 bg-border/20 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all"
            style={{ width: `${barWidth}%`, backgroundColor: color }}
          />
        </div>
        <span className="text-xs text-foreground/80 w-8 text-right shrink-0">
          {detail.score}/10
        </span>
        {seedDelta !== 0 && (
          <span
            className={`text-[9px] w-10 text-right shrink-0 ${
              seedDelta > 0 ? "text-emerald-400" : "text-red-400"
            }`}
          >
            {seedDelta > 0 ? "+" : ""}{seedDelta} seed
          </span>
        )}
        {seedDelta === 0 && (
          <span className="text-[9px] text-muted-foreground/30 w-10 text-right shrink-0">
            — seed
          </span>
        )}
        <span className="text-muted-foreground/40 text-xs ml-1">
          {expanded ? "▲" : "▼"}
        </span>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="px-3 pb-3 pt-1 space-y-3 border-t border-border/10">
          {detail.evidence && (
            <div>
              <div className="text-[9px] tracking-[2px] text-muted-foreground/40 uppercase mb-1">
                Evidence
              </div>
              <p className="text-[11px] text-muted-foreground/70 leading-relaxed">
                {detail.evidence}
              </p>
            </div>
          )}
          {detail.improve && (
            <div>
              <div className="text-[9px] tracking-[2px] text-muted-foreground/40 uppercase mb-1">
                What Would Make It Better
              </div>
              <p className="text-[11px] text-muted-foreground/70 leading-relaxed">
                {detail.improve}
              </p>
            </div>
          )}
          {nextIteration && nextActed && (
            <div className="text-[9px] text-purple-400/70">
              → i{nextIteration.iteration} acted on this:{" "}
              <span className="text-purple-400">{nextIteration.key_change}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
