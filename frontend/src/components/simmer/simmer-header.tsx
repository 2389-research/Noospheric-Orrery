"use client";

import Link from "next/link";
import { SimmerJobDetail } from "@/lib/types";

function timeSince(dateStr: string): string {
  // Ensure UTC parsing — timestamps from SQLite lack timezone suffix
  const utcStr = dateStr.includes("Z") || dateStr.includes("+") ? dateStr : dateStr + "Z";
  const seconds = Math.floor((Date.now() - new Date(utcStr).getTime()) / 1000);
  if (seconds < 0) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function getStartedAt(job: SimmerJobDetail): string {
  // Try to get the earliest created_at from iterations
  const allIterations = Object.values(job.phases).flat();
  if (allIterations.length > 0) {
    const sorted = [...allIterations].sort((a, b) =>
      new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    );
    return sorted[0].created_at;
  }
  return new Date().toISOString();
}

export function SimmerHeader({ job }: { job: SimmerJobDetail }) {
  const shortId = job.job_id.slice(0, 8);
  const startedAt = getStartedAt(job);
  const isRunning = job.status === "running";
  const isCompleted = job.status === "completed";
  const isFailed = job.status === "failed";

  return (
    <div className="flex items-start justify-between">
      <div className="space-y-1">
        <div className="text-[10px] tracking-[2px] text-muted-foreground/50 uppercase">
          <Link href="/pipeline" className="hover:text-muted-foreground transition-colors">jobs</Link>
          <span className="mx-1">/</span>
          <span className="text-muted-foreground/70">{shortId}</span>
          <span className="mx-2 text-muted-foreground/30">·</span>
          <span className="text-muted-foreground/60">{job.job_type}</span>
        </div>
        <div className="text-[10px] text-muted-foreground/40">
          <span>{job.target}</span>
          <span className="mx-2">·</span>
          <span>started {timeSince(startedAt)}</span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        {isRunning && (
          <div className="flex items-center gap-2 text-[10px] text-amber-400">
            <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
            <span className="tracking-[2px] uppercase">simmering</span>
          </div>
        )}
        {isCompleted && (
          <div className="flex items-center gap-2 text-[10px] text-emerald-400">
            <span className="w-2 h-2 rounded-full bg-emerald-400" />
            <span className="tracking-[2px] uppercase">completed</span>
          </div>
        )}
        {isFailed && (
          <div className="flex items-center gap-2 text-[10px] text-red-400">
            <span className="w-2 h-2 rounded-full bg-red-400" />
            <span className="tracking-[2px] uppercase">failed</span>
          </div>
        )}
      </div>
    </div>
  );
}
