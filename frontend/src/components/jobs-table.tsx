"use client";
import { Badge } from "@/components/ui/badge";
import { JobInfo } from "@/lib/types";

const statusStyle: Record<string, string> = {
  queued: "border-yellow-500/40 text-yellow-400",
  running: "border-cyan-400 text-cyan-400",
  completed: "border-emerald-500/40 text-emerald-400",
  failed: "border-red-500/40 text-red-400",
};

export function JobsTable({ jobs }: { jobs: JobInfo[] }) {
  if (jobs.length === 0) return <p className="text-muted-foreground/90 text-xs">No jobs</p>;
  return (
    <div className="rounded border border-border/30">
      {jobs.map((j) => (
        <div key={j.id} className="flex items-center gap-3 px-3 py-1.5 border-b border-border/10 last:border-0 text-xs hover:bg-card/50 transition-colors">
          <Badge variant="outline" className={`text-[9px] ${statusStyle[j.status] || ""}`}>{j.status}</Badge>
          <span className="text-foreground/85">{j.type}</span>
          <span className="text-muted-foreground/90">{j.target}</span>
          <span className="text-muted-foreground/85 ml-auto text-[10px]">{new Date(j.created_at).toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
}
