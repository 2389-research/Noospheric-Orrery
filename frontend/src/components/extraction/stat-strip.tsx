"use client";

import type { JobInfo, BatchResults } from "@/lib/types";

function formatDuration(started: string | null, completed: string | null): string {
  if (!started) return "—";
  const start = new Date(started.includes("Z") || started.includes("+") ? started : started + "Z").getTime();
  const end = completed
    ? new Date(completed.includes("Z") || completed.includes("+") ? completed : completed + "Z").getTime()
    : Date.now();
  const secs = Math.floor((end - start) / 1000);
  if (secs < 60) return `${secs}s`;
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}m ${s}s`;
}

function formatAvgDuration(started: string | null, completed: string | null, docs: number): string {
  if (!started || !completed || docs === 0) return "—";
  const start = new Date(started.includes("Z") || started.includes("+") ? started : started + "Z").getTime();
  const end = new Date(completed.includes("Z") || completed.includes("+") ? completed : completed + "Z").getTime();
  const avg = (end - start) / docs / 1000;
  return `${avg.toFixed(1)}s avg`;
}

interface StatStripProps {
  job: (JobInfo & { results?: BatchResults }) | null;
  typeNames: string[];
  totalMerges: number;
  isRunning: boolean;
}

export function StatStrip({ job, typeNames, totalMerges, isRunning }: StatStripProps) {
  const results = job?.results;
  const progress = job?.progress;
  const hasLiveProgress = isRunning && !!progress && progress.docs_total > 0;
  const pct = hasLiveProgress
    ? Math.min(100, Math.round((progress.docs_done / progress.docs_total) * 100))
    : 0;
  const docsProcessed = results?.docs_processed ?? 0;
  const entitiesFound = results?.entities_found ?? 0;
  const entitiesNew = results?.entities_new ?? 0;
  const entitiesMatched = results?.entities_matched ?? 0;
  const typeCount = typeNames.length;
  const duration = formatDuration(job?.started_at ?? null, job?.completed_at ?? null);
  const avgDuration = formatAvgDuration(job?.started_at ?? null, job?.completed_at ?? null, docsProcessed);

  const typeAbbreviations: Record<string, string> = {
    Person: "Per",
    Organization: "Org",
    Product: "Pro",
    Technology: "Tech",
    Event: "Evt",
    Concept: "Con",
    Location: "Loc",
  };

  const typeSubLabel = typeNames
    .slice(0, 3)
    .map((t) => typeAbbreviations[t] ?? t.slice(0, 3))
    .join("·");

  return (
    <div className="grid grid-cols-5 border border-border/30 rounded overflow-hidden">
      {/* DOCS */}
      <div className="px-4 py-3 border-r border-border/30">
        {hasLiveProgress ? (
          <>
            <p className="text-xl font-bold text-blue-400">
              {progress?.docs_done ?? 0}
              <span className="text-sm font-medium text-muted-foreground/60">/{progress?.docs_total ?? 0}</span>
            </p>
            <div className="h-1 mt-1.5 rounded-full bg-border/40 overflow-hidden">
              <div
                className="h-full bg-blue-400 transition-all duration-500"
                style={{ width: `${pct}%` }}
              />
            </div>
            <p className="text-[9px] tracking-[3px] text-muted-foreground/90 mt-1">DOCS</p>
            <p className="text-[9px] text-muted-foreground/70 mt-0.5">{pct}% · extracting…</p>
          </>
        ) : (
          <>
            <p className="text-xl font-bold text-blue-400">
              {isRunning && docsProcessed === 0 ? (
                <span className="animate-pulse text-muted-foreground/70">—</span>
              ) : (
                docsProcessed
              )}
            </p>
            <p className="text-[9px] tracking-[3px] text-muted-foreground/90 mt-1">DOCS</p>
            <p className="text-[9px] text-muted-foreground/70 mt-0.5">
              {job?.status === "failed" ? (
                <span className="text-red-400/80">partial results</span>
              ) : (
                "all extracted"
              )}
            </p>
          </>
        )}
      </div>

      {/* ENTITIES */}
      <div className="px-4 py-3 border-r border-border/30">
        {isRunning && !results ? (
          <>
            {progress ? (
              <p className="text-xl font-bold text-emerald-400">{progress.entities_so_far}</p>
            ) : (
              <p className="text-xl font-bold text-muted-foreground/70 animate-pulse">—</p>
            )}
            <p className="text-[9px] tracking-[3px] text-muted-foreground/90 mt-1">ENTITIES</p>
            <p className="text-[9px] text-muted-foreground/70 mt-0.5">extracting…</p>
          </>
        ) : (
          <>
            <p className="text-xl font-bold text-emerald-400 flex items-baseline gap-1.5">
              {entitiesFound}
              {entitiesNew > 0 && (
                <span className="text-sm font-medium text-emerald-400/90">+{entitiesNew} new</span>
              )}
            </p>
            <p className="text-[9px] tracking-[3px] text-muted-foreground/90 mt-1">ENTITIES</p>
            <p className="text-[9px] text-muted-foreground/70 mt-0.5">
              {entitiesNew === 0 ? (
                <span className="text-muted-foreground/70">all matched existing</span>
              ) : (
                `${entitiesMatched} matched`
              )}
            </p>
          </>
        )}
      </div>

      {/* TYPES */}
      <div className="px-4 py-3 border-r border-border/30">
        <p className="text-xl font-bold text-purple-400">{typeCount > 0 ? typeCount : "—"}</p>
        <p className="text-[9px] tracking-[3px] text-muted-foreground/90 mt-1">TYPES</p>
        <p className="text-[9px] text-muted-foreground/70 mt-0.5">{typeSubLabel || "—"}</p>
      </div>

      {/* MERGES */}
      <div className="px-4 py-3 border-r border-border/30">
        {isRunning && !results ? (
          <>
            <p className="text-xl font-bold text-muted-foreground/70 animate-pulse">—</p>
            <p className="text-[9px] tracking-[3px] text-muted-foreground/90 mt-1">MERGES</p>
            <p className="text-[9px] text-muted-foreground/70 mt-0.5">after norm.</p>
          </>
        ) : (
          <>
            <p className="text-xl font-bold text-amber-400">{totalMerges}</p>
            <p className="text-[9px] tracking-[3px] text-muted-foreground/90 mt-1">MERGES</p>
            <p className="text-[9px] text-muted-foreground/70 mt-0.5">after normalization</p>
          </>
        )}
      </div>

      {/* DURATION */}
      <div className="px-4 py-3">
        <p className="text-xl font-bold text-cyan-400">{duration}</p>
        <p className="text-[9px] tracking-[3px] text-muted-foreground/90 mt-1">DURATION</p>
        <p className="text-[9px] text-muted-foreground/70 mt-0.5">{avgDuration}</p>
      </div>
    </div>
  );
}
