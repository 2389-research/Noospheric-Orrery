"use client";

import Link from "next/link";
import type { EntityWithNew } from "@/lib/types";

const TYPE_COLORS: Record<string, { bg: string; text: string }> = {
  Person:       { bg: "#1a2a3a", text: "#378ADD" },
  Organization: { bg: "#2a1f2a", text: "#7F77DD" },
  Product:      { bg: "#1a2a24", text: "#1D9E75" },
  Technology:   { bg: "#2a251a", text: "#BA7517" },
  Event:        { bg: "#2a1a1a", text: "#D85A30" },
  Concept:      { bg: "#1e1e2a", text: "#9c9a92" },
  Location:     { bg: "#1a2420", text: "#5DCAA5" },
};

function TypeBadge({ type }: { type: string }) {
  const colors = TYPE_COLORS[type] ?? { bg: "#1a1a1a", text: "#888888" };
  return (
    <span
      className="text-[8px] tracking-[1px] uppercase px-1.5 py-0.5 rounded font-medium"
      style={{ backgroundColor: colors.bg, color: colors.text }}
    >
      {type}
    </span>
  );
}

function EntityCard({ entity }: { entity: EntityWithNew }) {
  return (
    <Link href={`/entities/${entity.id}`}>
      <div
        className={`border border-border/30 rounded p-2.5 hover:bg-card/40 transition-colors cursor-pointer h-full flex flex-col justify-between gap-1.5 ${
          entity.is_new ? "border-l-2 border-l-emerald-500" : ""
        }`}
      >
        <span className="text-[11px] text-foreground/90 truncate leading-tight font-medium">
          {entity.canonical_name}
        </span>
        <div className="flex items-center justify-between gap-1 flex-wrap">
          <TypeBadge type={entity.type} />
          <span className="text-[9px] text-muted-foreground/70 shrink-0">
            {entity.is_new && (
              <span className="text-emerald-400/90 mr-1">new·</span>
            )}
            {entity.source_count} docs
          </span>
        </div>
      </div>
    </Link>
  );
}

interface EntityPanelProps {
  entities: EntityWithNew[];
  activeTab: string;
  onTabChange: (tab: string) => void;
  entitiesNew: number;
  selectedDocTitle: string | null;
  isFailed: boolean;
}

export function EntityPanel({
  entities,
  activeTab,
  onTabChange,
  entitiesNew,
  selectedDocTitle,
  isFailed,
}: EntityPanelProps) {
  // Build available type tabs from entities
  const typeSet = new Set(entities.map((e) => e.type));
  const typeTabs = Array.from(typeSet).sort();

  const tabs = [
    "all",
    ...(entitiesNew > 0 ? ["new"] : []),
    ...typeTabs.map((t) => t.toLowerCase()),
  ];

  // Filter entities by tab
  const filtered = entities.filter((e) => {
    if (activeTab === "all") return true;
    if (activeTab === "new") return e.is_new === true;
    return e.type.toLowerCase() === activeTab;
  });

  // Sort: new first, then by source_count desc
  const sorted = [...filtered].sort((a, b) => {
    if (a.is_new && !b.is_new) return -1;
    if (!a.is_new && b.is_new) return 1;
    return b.source_count - a.source_count;
  });

  const panelTitle = selectedDocTitle
    ? `${selectedDocTitle} · ${entities.length} entities`
    : `All entities · ${entities.length}`;

  return (
    <div className="border border-border/30 rounded overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between gap-4 px-4 py-2 border-b border-border/20 flex-wrap">
        <span className="text-[11px] text-muted-foreground/90">{panelTitle}</span>
        <div className="flex items-center gap-1 flex-wrap">
          {tabs.map((tab) => (
            <button
              key={tab}
              onClick={() => onTabChange(tab)}
              className={`text-[9px] tracking-[1px] uppercase px-2 py-1 rounded transition-colors border ${
                activeTab === tab
                  ? "border-cyan-500/50 bg-cyan-500/10 text-cyan-400"
                  : "border-border/30 text-muted-foreground/70 hover:text-muted-foreground hover:border-border/50"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {/* Failed warning */}
      {isFailed && (
        <div className="px-4 py-2 bg-red-500/5 border-b border-red-500/20">
          <span className="text-[10px] text-red-400/90">
            extraction failed — partial results shown
          </span>
        </div>
      )}

      {/* Grid */}
      <div className="p-3">
        {sorted.length === 0 ? (
          <div className="flex items-center justify-center py-12">
            <p className="text-[11px] text-muted-foreground/60">
              {activeTab === "new"
                ? "no new entities in this batch"
                : activeTab === "all"
                ? "no entities extracted — check spec configuration"
                : `no entities of this type in batch`}
            </p>
          </div>
        ) : (
          <div
            className="grid gap-px"
            style={{
              gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
              backgroundColor: "var(--border)",
            }}
          >
            {sorted.map((entity) => (
              <div key={entity.id} className="bg-background">
                <EntityCard entity={entity} />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
