"use client";

import type { EntityWithNew } from "@/lib/types";

const TYPE_COLORS: Record<string, string> = {
  Person:       "#378ADD",
  Organization: "#7F77DD",
  Product:      "#1D9E75",
  Technology:   "#BA7517",
  Event:        "#D85A30",
  Concept:      "#9c9a92",
  Location:     "#5DCAA5",
};

const TYPE_ORDER = ["Person", "Organization", "Product", "Technology", "Concept", "Event", "Location"];

interface TypeDistributionProps {
  entities: EntityWithNew[];
  activeType: string | null;
  onTypeClick: (type: string) => void;
}

export function TypeDistribution({ entities, activeType, onTypeClick }: TypeDistributionProps) {
  // Build counts by type
  const countByType: Record<string, number> = {};
  const newByType: Record<string, number> = {};
  for (const e of entities) {
    countByType[e.type] = (countByType[e.type] ?? 0) + 1;
    if (e.is_new) newByType[e.type] = (newByType[e.type] ?? 0) + 1;
  }

  const types = TYPE_ORDER.filter((t) => countByType[t] !== undefined);
  // also include any types not in TYPE_ORDER
  for (const t of Object.keys(countByType)) {
    if (!types.includes(t)) types.push(t);
  }

  const maxCount = types.length > 0 ? Math.max(...types.map((t) => countByType[t] ?? 0)) : 1;

  return (
    <div className="border border-border/30 rounded overflow-hidden">
      <div className="px-4 py-2 border-b border-border/20">
        <span className="text-[9px] tracking-[3px] text-muted-foreground/90 uppercase">
          Entity Type Distribution
        </span>
      </div>
      <div className="p-3 space-y-2">
        {types.length === 0 ? (
          <p className="text-[10px] text-muted-foreground/70 py-2">no entities yet</p>
        ) : (
          types.map((type) => {
            const count = countByType[type] ?? 0;
            const newCount = newByType[type] ?? 0;
            const barPct = maxCount > 0 ? (count / maxCount) * 100 : 0;
            const color = TYPE_COLORS[type] ?? "#888888";
            const isActive = activeType === type.toLowerCase();

            return (
              <button
                key={type}
                className={`w-full flex items-center gap-2 group transition-opacity hover:opacity-90 focus:outline-none ${
                  isActive ? "opacity-100" : ""
                }`}
                onClick={() => onTypeClick(type.toLowerCase())}
              >
                <span className="text-[10px] text-muted-foreground/80 w-[90px] shrink-0 text-left truncate">
                  {type}
                </span>
                <div className="flex-1 h-[6px] bg-border/20 rounded overflow-hidden">
                  <div
                    className="h-full rounded transition-all duration-300"
                    style={{
                      width: `${barPct}%`,
                      backgroundColor: color,
                      opacity: 0.7,
                    }}
                  />
                </div>
                <span className="text-[10px] text-muted-foreground/80 w-6 text-right shrink-0">
                  {count}
                </span>
                <span className="text-[10px] w-8 text-right shrink-0">
                  {newCount > 0 ? (
                    <span className="text-emerald-400/90">+{newCount}</span>
                  ) : (
                    <span className="text-muted-foreground/70">—</span>
                  )}
                </span>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
