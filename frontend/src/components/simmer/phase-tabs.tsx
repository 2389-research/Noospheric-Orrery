"use client";

import { SimmerJobDetail, SimmerIteration } from "@/lib/types";

const PHASE_LABELS: Record<string, string> = {
  golden_set: "Golden Set",
  extraction_spec: "Extraction Spec",
};

function bestComposite(iterations: SimmerIteration[]): number | null {
  if (iterations.length === 0) return null;
  return Math.max(...iterations.map((i) => i.composite));
}

interface PhaseTabsProps {
  job: SimmerJobDetail;
  activePhase: string;
  onPhaseChange: (phase: string) => void;
}

export function PhaseTabs({ job, activePhase, onPhaseChange }: PhaseTabsProps) {
  // Golden set runs first, extraction spec second
  const PHASE_ORDER = ["golden_set", "extraction_spec"];
  const phases = PHASE_ORDER.filter((p) => p in job.phases || PHASE_ORDER.includes(p));

  return (
    <div className="flex gap-0 border-b border-border/30">
      {phases.map((phase) => {
        const iterations = job.phases[phase] ?? [];
        const isEmpty = iterations.length === 0;
        const isActive = phase === activePhase;
        const best = bestComposite(iterations);

        return (
          <button
            key={phase}
            onClick={() => !isEmpty && onPhaseChange(phase)}
            disabled={isEmpty}
            className={[
              "px-4 py-2.5 text-[10px] tracking-[2px] uppercase transition-colors relative",
              isActive
                ? "text-foreground/90 border-t-2 border-purple-500"
                : isEmpty
                ? "text-muted-foreground/45 cursor-not-allowed"
                : "text-muted-foreground/50 hover:text-muted-foreground/80 cursor-pointer border-t-2 border-transparent",
            ].join(" ")}
          >
            <span>{PHASE_LABELS[phase] ?? phase}</span>
            {!isEmpty && (
              <span className={`ml-2 text-[9px] ${isActive ? "text-muted-foreground/50" : "text-muted-foreground/50"}`}>
                {iterations.length} iter
                {best !== null && (
                  <span className="ml-1 text-purple-400/70">{best.toFixed(1)}</span>
                )}
              </span>
            )}
            {isEmpty && (
              <span className="ml-2 text-[9px] text-muted-foreground/40">—</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
