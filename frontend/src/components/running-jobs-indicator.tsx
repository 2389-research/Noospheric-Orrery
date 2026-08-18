"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { JobInfo } from "@/lib/types";

// A compact "job running" badge in the nav (issue #51). Polls the job list and, when an
// extraction is active, links straight to its detail page (where the real progress bar lives).
export function RunningJobsIndicator({ noosphereId }: { noosphereId: string }) {
  const [active, setActive] = useState<JobInfo[]>([]);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const jobs = await api.getJobs();
        if (!alive) return;
        setActive(jobs.filter((j) => j.status === "running" || j.status === "queued"));
      } catch {
        /* transient — keep the last known state */
      }
    };
    poll();
    const t = setInterval(poll, 5000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [noosphereId]);

  if (active.length === 0) return null;

  const label = active.length === 1 ? "1 job running" : `${active.length} jobs running`;
  const badge = (
    <span className="flex items-center gap-1.5 px-2.5 py-1 text-[10px] tracking-wider rounded-full bg-blue-500/15 text-blue-300 border border-blue-400/20">
      <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
      {label}
    </span>
  );

  const extract = active.find((j) => j.type === "extract_batch");
  return extract ? (
    <Link href={`/n/${noosphereId}/extraction/${extract.id}`} title="View extraction progress">
      {badge}
    </Link>
  ) : (
    badge
  );
}
