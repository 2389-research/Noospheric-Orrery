"use client";
import { Badge } from "@/components/ui/badge";
import { EntitySummary } from "@/lib/types";

const typeColors: Record<string, string> = {
  Person: "border-blue-500/40 text-blue-400",
  Organization: "border-purple-500/40 text-purple-400",
  Location: "border-emerald-500/40 text-emerald-400",
  Product: "border-orange-500/40 text-orange-400",
  Technology: "border-cyan-500/40 text-cyan-400",
  Event: "border-yellow-500/40 text-yellow-400",
  Concept: "border-pink-500/40 text-pink-400",
};

export function EntityTable({ entities }: { entities: EntitySummary[] }) {
  if (entities.length === 0) return <p className="text-muted-foreground/85 text-xs">No entities yet</p>;
  return (
    <div className="rounded border border-border/30">
      <div className="grid grid-cols-4 gap-4 px-4 py-2 border-b border-border/20 text-[9px] tracking-[2px] text-muted-foreground/85 uppercase">
        <span>Name</span><span>Type</span><span>Sources</span><span></span>
      </div>
      {entities.map((e) => (
        <div key={e.id} className="grid grid-cols-4 gap-4 px-4 py-2 border-b border-border/10 last:border-0 text-xs hover:bg-card/50 transition-colors">
          <span className="text-foreground/90">{e.canonical_name}</span>
          <Badge variant="outline" className={`w-fit text-[10px] ${typeColors[e.type] || "border-muted-foreground/85 text-muted-foreground"}`}>
            {e.type}
          </Badge>
          <span className="text-muted-foreground/90">{e.source_count}</span>
          <a href={`/entities/${e.id}`} className="text-cyan-500/70 hover:text-cyan-400 transition-colors">→</a>
        </div>
      ))}
    </div>
  );
}
