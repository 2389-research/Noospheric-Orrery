"use client";

import Link from "next/link";
import type { JobInfo, BatchResults } from "@/lib/types";
import { useNoosphereId } from "@/lib/hooks/use-noosphere-id";

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

interface ExtractionHeaderProps {
  job: (JobInfo & { results?: BatchResults }) | null;
}

export function ExtractionHeader({ job }: ExtractionHeaderProps) {
  const noosphereId = useNoosphereId();
  if (!job) return null;

  const shortId = job.id.slice(0, 8);
  const specVersion = job.results?.spec_version ?? job.target ?? "—";
  const duration = formatDuration(job.started_at, job.completed_at);
  const docsProcessed = job.results?.docs_processed ?? 0;

  return (
    <div className="flex items-start justify-between">
      <div className="space-y-1">
        <div className="text-[10px] tracking-[2px] text-muted-foreground/85 uppercase">
          <Link href={`/n/${noosphereId}/pipeline`} className="hover:text-muted-foreground transition-colors">
            jobs
          </Link>
          <span className="mx-1">/</span>
          <span className="text-muted-foreground/85">{shortId}</span>
          <span className="mx-2 text-muted-foreground/85">·</span>
          <span className="text-muted-foreground/90">extract_batch</span>
          <span className="mx-2 text-muted-foreground/85">·</span>
          <span className="text-muted-foreground/85">{specVersion}</span>
        </div>
        <div className="text-sm text-foreground/90 font-medium">
          Batch extraction
          {docsProcessed > 0 && (
            <span className="text-muted-foreground/85 font-normal"> · {docsProcessed} documents</span>
          )}
        </div>
        <div className="text-[10px] text-muted-foreground/85">
          {job.status === "completed" && (
            <>
              <span>completed in {duration}</span>
              <span className="mx-2">·</span>
              <span>spec: {specVersion}</span>
            </>
          )}
          {job.status === "running" && (
            <span>started · extracting…</span>
          )}
          {job.status === "failed" && (
            <span>failed after {duration}</span>
          )}
          {job.status === "queued" && (
            <span>queued</span>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2">
        {job.status === "running" && (
          <div className="flex items-center gap-2 text-[10px] text-amber-400">
            <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
            <span className="tracking-[2px] uppercase">extracting</span>
          </div>
        )}
        {job.status === "completed" && (
          <div className="flex items-center gap-2 text-[10px] text-emerald-400">
            <span className="w-2 h-2 rounded-full bg-emerald-400" />
            <span className="tracking-[2px] uppercase">completed</span>
          </div>
        )}
        {job.status === "failed" && (
          <div className="flex items-center gap-2 text-[10px] text-red-400">
            <span className="w-2 h-2 rounded-full bg-red-400" />
            <span className="tracking-[2px] uppercase">failed</span>
          </div>
        )}
        {job.status === "queued" && (
          <div className="flex items-center gap-2 text-[10px] text-yellow-400">
            <span className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" />
            <span className="tracking-[2px] uppercase">queued</span>
          </div>
        )}
      </div>
    </div>
  );
}
