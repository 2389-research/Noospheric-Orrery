"use client";
import { Card } from "@/components/ui/card";
import { Stats } from "@/lib/types";

export function StatsBar({ stats }: { stats: Stats | null }) {
  if (!stats) return <div className="text-muted-foreground">Loading...</div>;
  const items = [
    { label: "Documents", value: stats.document_count },
    { label: "Entities", value: stats.entity_count },
    { label: "Domains", value: stats.domain_count },
    { label: "Active Jobs", value: stats.active_jobs },
  ];
  return (
    <div className="grid grid-cols-4 gap-4">
      {items.map((item) => (
        <Card key={item.label} className="p-4 text-center">
          <p className="text-2xl font-bold">{item.value}</p>
          <p className="text-sm text-muted-foreground">{item.label}</p>
        </Card>
      ))}
    </div>
  );
}
