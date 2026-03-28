"use client";

import { Stats, JobInfo } from "@/lib/types";

interface PipelineStagesProps {
  stats: Stats | null;
  jobs: JobInfo[];
}

type StageStatus = "idle" | "active" | "complete" | "waiting";

interface Stage {
  name: string;
  label: string;
  status: StageStatus;
  detail: string;
}

export function PipelineStages({ stats, jobs }: PipelineStagesProps) {
  if (!stats) return null;

  const hasGeneralSpec = jobs.some(
    (j) => j.type === "simmer_general" && j.status === "completed"
  );
  const simmeringNow = jobs.some(
    (j) => j.type === "simmer_general" && j.status === "running"
  );
  const extracting = jobs.some(
    (j) => j.type === "extract_batch" && j.status === "running"
  );
  const pendingDocs = stats.document_count > 0;

  const stages: Stage[] = [
    {
      name: "ingest",
      label: "INGEST",
      status: pendingDocs ? "complete" : "idle",
      detail: `${stats.document_count} docs`,
    },
    {
      name: "classify",
      label: "CLASSIFY",
      status: stats.domain_count > 0 ? "complete" : pendingDocs ? "active" : "idle",
      detail: `${stats.domain_count} domains`,
    },
    {
      name: "simmer",
      label: "SIMMER",
      status: simmeringNow
        ? "active"
        : hasGeneralSpec
          ? "complete"
          : pendingDocs
            ? "waiting"
            : "idle",
      detail: simmeringNow ? "simmering..." : hasGeneralSpec ? "spec ready" : "awaiting docs",
    },
    {
      name: "extract",
      label: "EXTRACT",
      status: extracting
        ? "active"
        : stats.entity_count > 0
          ? "complete"
          : hasGeneralSpec
            ? "waiting"
            : "idle",
      detail: `${stats.entity_count} entities`,
    },
    {
      name: "normalize",
      label: "NORMALIZE",
      status: stats.entity_count > 0 ? "complete" : "idle",
      detail: stats.entity_count > 0 ? "auto" : "",
    },
  ];

  const statusColor: Record<StageStatus, string> = {
    idle: "border-muted-foreground/20 text-muted-foreground/40",
    waiting: "border-yellow-500/40 text-yellow-500/70",
    active: "border-cyan-400 text-cyan-400 shadow-[0_0_12px_rgba(34,211,238,0.15)]",
    complete: "border-emerald-500/60 text-emerald-400",
  };

  const connectorColor: Record<StageStatus, string> = {
    idle: "bg-muted-foreground/10",
    waiting: "bg-yellow-500/20",
    active: "bg-cyan-400/40",
    complete: "bg-emerald-500/30",
  };

  const dotColor: Record<StageStatus, string> = {
    idle: "bg-muted-foreground/20",
    waiting: "bg-yellow-500/50 animate-pulse",
    active: "bg-cyan-400 animate-pulse shadow-[0_0_6px_rgba(34,211,238,0.4)]",
    complete: "bg-emerald-500/70",
  };

  return (
    <div className="flex items-center gap-0 w-full overflow-x-auto py-4">
      {stages.map((stage, i) => (
        <div key={stage.name} className="flex items-center">
          {/* Stage node */}
          <div
            className={`relative border rounded px-4 py-3 min-w-[120px] text-center transition-all ${statusColor[stage.status]}`}
          >
            <div className="text-[10px] tracking-[3px] font-bold">{stage.label}</div>
            <div className="text-[10px] mt-1 opacity-70">{stage.detail}</div>
            {/* Status dot */}
            <div
              className={`absolute -top-1 -right-1 w-2 h-2 rounded-full ${dotColor[stage.status]}`}
            />
          </div>
          {/* Connector */}
          {i < stages.length - 1 && (
            <div className="flex items-center mx-1">
              <div className={`h-[1px] w-8 ${connectorColor[stages[i + 1].status]}`} />
              <div className={`text-[8px] ${stages[i + 1].status === "idle" ? "text-muted-foreground/20" : "text-muted-foreground/50"}`}>
                ▸
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
