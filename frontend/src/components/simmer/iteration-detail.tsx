"use client";

import { SimmerIteration } from "@/lib/types";
import { TrajectoryChart } from "./trajectory-chart";
import { CriterionCard } from "./criterion-card";

const CRITERION_COLORS = ["#378ADD", "#BA7517", "#1D9E75", "#9B5E8A", "#6B7280"];

interface IterationDetailProps {
  iteration: SimmerIteration;
  allIterations: SimmerIteration[];
  selectedIndex: number;
  previousIteration?: SimmerIteration;
  nextIteration?: SimmerIteration;
}

export function IterationDetail({
  iteration,
  allIterations,
  selectedIndex,
  previousIteration,
  nextIteration,
}: IterationDetailProps) {
  const delta = previousIteration
    ? iteration.composite - previousIteration.composite
    : null;

  const criterionNames = Object.keys(iteration.scores);

  return (
    <div className="space-y-4">
      {/* Detail Header */}
      <div className="space-y-2">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="text-[9px] tracking-[2px] text-muted-foreground/90 uppercase mb-1">
              iteration {iteration.iteration} · {iteration.phase}
            </div>
            <h2 className="text-sm text-foreground/90 leading-snug">
              {(iteration.key_change || (iteration.iteration === 0 ? "Seed iteration" : "—")).replace(/^\*+\s*/, "")}
            </h2>
            {iteration.criterion_details.length > 0 && (
              <p className="text-[10px] text-muted-foreground/85 mt-1.5 leading-relaxed line-clamp-2">
                {iteration.criterion_details[0].evidence}
              </p>
            )}
            {iteration.iteration === 0 && iteration.criterion_details.length === 0 && (
              <p className="text-[10px] text-muted-foreground/90 mt-1.5">
                Starting point — judge feedback begins at iteration 1
              </p>
            )}
          </div>
          <div className="text-right shrink-0">
            <div className="text-2xl font-semibold" style={{ color: "#7F77DD" }}>
              {iteration.composite.toFixed(1)}
            </div>
            {delta !== null && (
              <div
                className={`text-[10px] ${
                  delta > 0
                    ? "text-emerald-400"
                    : delta < 0
                    ? "text-red-400"
                    : "text-muted-foreground/90"
                }`}
              >
                {delta > 0 ? `+${delta.toFixed(1)}` : delta < 0 ? delta.toFixed(1) : "—"}
              </div>
            )}
            {delta === null && (
              <div className="text-[10px] text-muted-foreground/85">seed</div>
            )}
          </div>
        </div>

        {/* Score strip */}
        <div className="flex gap-2 flex-wrap">
          {criterionNames.map((name, ci) => {
            const score = iteration.scores[name];
            const seedScore = allIterations[0]?.scores[name];
            const scoreDelta = seedScore !== undefined ? score - seedScore : null;
            const color = CRITERION_COLORS[ci % CRITERION_COLORS.length];

            return (
              <div
                key={name}
                className="flex items-center gap-1.5 px-2 py-1 border border-border/20 rounded"
              >
                <span
                  className="text-[9px] tracking-[1px] uppercase"
                  style={{ color }}
                >
                  {name}
                </span>
                <span className="text-xs text-foreground/90">{score}/10</span>
                {scoreDelta !== null && scoreDelta !== 0 && (
                  <span
                    className={`text-[9px] ${
                      scoreDelta > 0 ? "text-emerald-400" : "text-red-400"
                    }`}
                  >
                    {scoreDelta > 0 ? "+" : ""}{scoreDelta} seed
                  </span>
                )}
              </div>
            );
          })}
          {iteration.judge_mode && (
            <span className="text-[8px] text-muted-foreground/90 self-center ml-1">
              judge: {iteration.judge_mode}
            </span>
          )}
        </div>
      </div>

      {/* Trajectory Chart */}
      <div className="border border-border/20 rounded p-3">
        <div className="text-[9px] tracking-[2px] text-muted-foreground/90 uppercase mb-3">
          Score Trajectory
        </div>
        <TrajectoryChart iterations={allIterations} selectedIndex={selectedIndex} />
      </div>

      {/* Criterion Cards */}
      {iteration.criterion_details.length > 0 && (
        <div className="space-y-2">
          <div className="text-[9px] tracking-[2px] text-muted-foreground/90 uppercase">
            Criterion Details
          </div>
          {iteration.criterion_details.map((detail, idx) => {
            const colorIndex = criterionNames.indexOf(detail.criterion);
            return (
              <CriterionCard
                key={detail.criterion}
                detail={detail}
                colorIndex={colorIndex >= 0 ? colorIndex : idx}
                nextIteration={nextIteration}
              />
            );
          })}
        </div>
      )}

      {/* No detail message */}
      {iteration.criterion_details.length === 0 && (
        <div className="text-[10px] text-muted-foreground/85 py-4 text-center border border-border/10 rounded">
          No criterion details for this iteration
        </div>
      )}
    </div>
  );
}
