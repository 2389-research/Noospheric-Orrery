"use client";

import { Stats } from "@/lib/types";

export function StatsBar({ stats }: { stats: Stats | null }) {
  if (!stats) return <div className="text-muted-foreground/50 text-xs">Loading...</div>;
  const items = [
    { label: "DOCS", value: stats.document_count, color: "text-blue-400" },
    { label: "ENTITIES", value: stats.entity_count, color: "text-emerald-400" },
    { label: "DOMAINS", value: stats.domain_count, color: "text-purple-400" },
    { label: "ACTIVE", value: stats.active_jobs, color: stats.active_jobs > 0 ? "text-cyan-400" : "text-muted-foreground/50" },
  ];
  return (
    <div className="grid grid-cols-4 gap-4">
      {items.map((item) => (
        <div key={item.label} className="border border-border/30 rounded px-4 py-3">
          <p className={`text-2xl font-bold ${item.color}`}>{item.value}</p>
          <p className="text-[9px] tracking-[3px] text-muted-foreground/60 mt-1">{item.label}</p>
        </div>
      ))}
    </div>
  );
}
