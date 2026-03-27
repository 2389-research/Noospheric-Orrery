"use client";
import { Badge } from "@/components/ui/badge";
import { JobInfo } from "@/lib/types";

const statusColors: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  queued: "outline", running: "secondary", completed: "default", failed: "destructive",
};

export function JobsTable({ jobs }: { jobs: JobInfo[] }) {
  if (jobs.length === 0) return <p className="text-muted-foreground">No jobs</p>;
  return (
    <div className="space-y-1">
      {jobs.map((j) => (
        <div key={j.id} className="flex items-center gap-3 py-1 px-2 rounded hover:bg-muted text-sm">
          <Badge variant={statusColors[j.status] || "outline"}>{j.status}</Badge>
          <span className="font-mono">{j.type}</span>
          <span className="text-muted-foreground">{j.target}</span>
          <span className="text-muted-foreground ml-auto">{new Date(j.created_at).toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
}
