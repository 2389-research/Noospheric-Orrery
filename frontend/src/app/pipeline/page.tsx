"use client";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { StatsBar } from "@/components/stats-bar";
import { DomainTree } from "@/components/domain-tree";
import { NormalizationPanel } from "@/components/normalization-panel";
import { api } from "@/lib/api";
import type { Stats, DomainInfo, JobInfo } from "@/lib/types";

const jobStatusStyle: Record<string, string> = {
  queued: "border-yellow-500/40 text-yellow-400 animate-pulse",
  running: "border-cyan-400 text-cyan-400 animate-pulse",
  completed: "border-emerald-500/40 text-emerald-400",
  failed: "border-red-500/40 text-red-400",
};

function ActiveJobs({ jobs }: { jobs: JobInfo[] }) {
  const active = jobs.filter((j) => j.status === "running" || j.status === "queued");
  const recent = jobs.filter((j) => j.status === "completed" || j.status === "failed").slice(0, 3);

  if (active.length === 0 && recent.length === 0) return null;

  return (
    <div className="space-y-1.5">
      {active.map((j) => (
        <div key={j.id} className="flex items-center gap-3 border border-cyan-500/20 rounded px-3 py-2 bg-cyan-500/5">
          <Badge variant="outline" className={`text-[9px] ${jobStatusStyle[j.status]}`}>{j.status}</Badge>
          <span className="text-xs text-foreground/80">{j.type}</span>
          <span className="text-[10px] text-muted-foreground/50">{j.target}</span>
          <span className="text-[10px] text-muted-foreground/30 ml-auto">{timeSince(j.started_at || j.created_at)}</span>
        </div>
      ))}
      {recent.map((j) => (
        <div key={j.id} className="flex items-center gap-3 px-3 py-1.5 text-xs">
          <Badge variant="outline" className={`text-[9px] ${jobStatusStyle[j.status]}`}>{j.status}</Badge>
          <span className="text-muted-foreground/60">{j.type}</span>
          <span className="text-[10px] text-muted-foreground/30">{j.target}</span>
          <span className="text-[10px] text-muted-foreground/20 ml-auto">{timeSince(j.completed_at || j.created_at)}</span>
        </div>
      ))}
    </div>
  );
}

function timeSince(dateStr: string): string {
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export default function PipelinePage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [domains, setDomains] = useState<DomainInfo[]>([]);
  const [jobs, setJobs] = useState<JobInfo[]>([]);

  const refresh = async () => {
    const [s, d, j] = await Promise.all([api.getStats(), api.getDomains(), api.getJobs()]);
    setStats(s); setDomains(d); setJobs(j);
  };

  useEffect(() => { refresh(); const interval = setInterval(refresh, 5000); return () => clearInterval(interval); }, []);

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <h1 className="text-sm tracking-[4px] text-muted-foreground uppercase">Pipeline</h1>

      {/* Stats row */}
      <StatsBar stats={stats} />

      {/* Active jobs — prominent if running */}
      <ActiveJobs jobs={jobs} />

      {/* Two-column layout: domains + normalization */}
      <div className="grid grid-cols-2 gap-6">
        <section>
          <h2 className="text-xs tracking-[3px] text-muted-foreground/50 uppercase mb-3">Domains</h2>
          <DomainTree domains={domains} />
        </section>
        <section>
          <NormalizationPanel />
        </section>
      </div>
    </div>
  );
}
