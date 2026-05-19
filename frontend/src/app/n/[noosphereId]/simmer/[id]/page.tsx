"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { SimmerJobDetail, SimmerIteration } from "@/lib/types";
import { SimmerHeader } from "@/components/simmer/simmer-header";
import { PhaseTabs } from "@/components/simmer/phase-tabs";
import { IterationList } from "@/components/simmer/iteration-list";
import { IterationDetail } from "@/components/simmer/iteration-detail";

export default function SimmerPage() {
  const params = useParams();
  const jobId = params.id as string;

  const [job, setJob] = useState<SimmerJobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activePhase, setActivePhase] = useState<string>("");
  const [selectedIndex, setSelectedIndex] = useState<number>(0);
  const [visibleCount, setVisibleCount] = useState<number | null>(null);

  const fetchJob = useCallback(async () => {
    try {
      const data = await api.getJobIterations(jobId);
      setJob((prev) => {
        // Set initial active phase if not set
        if (!prev) {
          const PHASE_ORDER = ["golden_set", "extraction_spec", "domain_image_spec"];
          const firstNonEmpty = PHASE_ORDER.find((p) => (data.phases[p]?.length ?? 0) > 0);
          if (firstNonEmpty) {
            setActivePhase(firstNonEmpty);
            const iters = data.phases[firstNonEmpty] ?? [];
            setSelectedIndex(Math.max(0, iters.length - 1));
          }
        } else {
          // If active phase grows, update selected to last
          if (activePhase) {
            const newIters = data.phases[activePhase] ?? [];
            const oldIters = prev.phases[activePhase] ?? [];
            if (newIters.length > oldIters.length && selectedIndex === oldIters.length - 1) {
              setSelectedIndex(newIters.length - 1);
            }
          }
        }
        return data;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load job");
    }
  }, [jobId, activePhase, selectedIndex]);

  useEffect(() => {
    fetchJob();
  }, [jobId]);

  useEffect(() => {
    if (!job) return;
    if (job.status !== "running") return;
    const interval = setInterval(fetchJob, 5000);
    return () => clearInterval(interval);
  }, [job, fetchJob]);

  const handlePhaseChange = (phase: string) => {
    setActivePhase(phase);
    if (job) {
      const iters = job.phases[phase] ?? [];
      setSelectedIndex(Math.max(0, iters.length - 1));
    }
  };

  if (error) {
    return (
      <div className="max-w-5xl mx-auto py-12 text-center">
        <p className="text-red-400 text-sm">{error}</p>
      </div>
    );
  }

  if (!job) {
    return (
      <div className="max-w-5xl mx-auto py-12 text-center">
        <p className="text-muted-foreground/90 text-xs tracking-[2px] animate-pulse">
          loading...
        </p>
      </div>
    );
  }

  const iterations: SimmerIteration[] = (activePhase && job.phases[activePhase]) ? job.phases[activePhase] : [];
  const selectedIteration = iterations[selectedIndex] ?? null;
  const previousIteration = selectedIndex > 0 ? iterations[selectedIndex - 1] : undefined;
  const nextIteration =
    selectedIndex < iterations.length - 1 ? iterations[selectedIndex + 1] : undefined;

  return (
    <div className="max-w-6xl mx-auto space-y-4">
      <SimmerHeader job={job} />
      <PhaseTabs job={job} activePhase={activePhase} onPhaseChange={handlePhaseChange} />

      <div className="flex gap-0 border border-border/30 rounded overflow-hidden" style={{ minHeight: "500px" }}>
        {/* Left column: iteration list */}
        <div className="w-[200px] shrink-0 border-r border-border/20 overflow-y-auto">
          <IterationList
            iterations={iterations}
            selectedIndex={selectedIndex}
            onSelect={setSelectedIndex}
            isRunning={job.status === "running"}
            isCompleted={job.status === "completed"}
            onVisibleCountChange={setVisibleCount}
            bestIndex={iterations.length > 0
              ? iterations.reduce((best, iter, idx) => iter.composite > iterations[best].composite ? idx : best, 0)
              : undefined
            }
          />
        </div>

        {/* Right column: iteration detail */}
        <div className="flex-1 overflow-y-auto p-4">
          {selectedIteration ? (
            <IterationDetail
              iteration={selectedIteration}
              allIterations={visibleCount !== null ? iterations.slice(0, visibleCount) : iterations}
              selectedIndex={selectedIndex}
              previousIteration={previousIteration}
              nextIteration={nextIteration}
            />
          ) : (
            <div className="flex items-center justify-center h-full">
              <p className="text-muted-foreground/85 text-xs tracking-[2px]">
                No iterations yet
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
