"use client";
import { Badge } from "@/components/ui/badge";
import { EntitySummary } from "@/lib/types";

export function EntityTable({ entities }: { entities: EntitySummary[] }) {
  if (entities.length === 0) return <p className="text-muted-foreground">No entities yet</p>;
  return (
    <div className="rounded-md border">
      <div className="grid grid-cols-4 gap-4 p-3 border-b font-medium text-sm">
        <span>Name</span><span>Type</span><span>Sources</span><span></span>
      </div>
      {entities.map((e) => (
        <div key={e.id} className="grid grid-cols-4 gap-4 p-3 border-b last:border-0 text-sm hover:bg-muted">
          <span className="font-medium">{e.canonical_name}</span>
          <Badge variant="outline">{e.type}</Badge>
          <span className="text-muted-foreground">{e.source_count} docs</span>
          <a href={`/entities/${e.id}`} className="text-primary hover:underline">detail</a>
        </div>
      ))}
    </div>
  );
}
