"use client";
import { useEffect, useState, useMemo } from "react";
import { EntityTable } from "@/components/entity-table";
import { api } from "@/lib/api";
import { useNoosphereId } from "@/lib/hooks/use-noosphere-id";
import type { EntitySummary } from "@/lib/types";

const TYPE_COLORS: Record<string, string> = {
  Person: "#378ADD",
  Organization: "#7F77DD",
  Product: "#1D9E75",
  Technology: "#BA7517",
  Event: "#D85A30",
  Concept: "#9c9a92",
  Location: "#5DCAA5",
  Decision: "#6B8E9B",
  ActionItem: "#C97B4B",
  Deliverable: "#8B6BAE",
  BusinessConcept: "#A0926B",
  Domain: "#5A8A6B",
  Thing: "#8A8A8A",
  FundingAmount: "#C9A84B",
  InvestmentFirm: "#7F77DD",
  BusinessMetric: "#A0926B",
};

export default function EntitiesPage() {
  const noosphereId = useNoosphereId();
  const [entities, setEntities] = useState<EntitySummary[]>([]);
  const [allEntities, setAllEntities] = useState<EntitySummary[]>([]);
  const [typeFilter, setTypeFilter] = useState("");
  const [searchFilter, setSearchFilter] = useState("");

  useEffect(() => {
    api.getEntities({ limit: 10000 }).then((data) => {
      setAllEntities(data);
      setEntities(data);
    }).catch(console.error);
  }, []);

  useEffect(() => {
    let filtered = allEntities;
    if (typeFilter) {
      filtered = filtered.filter((e) => e.type === typeFilter);
    }
    if (searchFilter.trim()) {
      const q = searchFilter.toLowerCase();
      filtered = filtered.filter((e) => e.canonical_name.toLowerCase().includes(q));
    }
    setEntities(filtered);
  }, [typeFilter, searchFilter, allEntities]);

  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const e of allEntities) {
      counts[e.type] = (counts[e.type] || 0) + 1;
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [allEntities]);

  const topEntities = useMemo(() => {
    return [...allEntities].sort((a, b) => b.source_count - a.source_count).slice(0, 5);
  }, [allEntities]);

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-sm tracking-[4px] text-muted-foreground uppercase">Entities</h1>
          <span className="text-xs text-muted-foreground/70">{allEntities.length} total</span>
        </div>

        <div className="grid grid-cols-4 gap-3">
          <div className="rounded border border-border/30 p-3">
            <div className="text-[9px] tracking-[2px] text-muted-foreground/70 uppercase mb-1">Total</div>
            <div className="text-2xl font-light text-foreground/90">{allEntities.length}</div>
          </div>
          <div className="rounded border border-border/30 p-3">
            <div className="text-[9px] tracking-[2px] text-muted-foreground/70 uppercase mb-1">Types</div>
            <div className="text-2xl font-light text-foreground/90">{typeCounts.length}</div>
          </div>
          <div className="rounded border border-border/30 p-3">
            <div className="text-[9px] tracking-[2px] text-muted-foreground/70 uppercase mb-1">Most Common</div>
            <div className="text-lg font-light text-foreground/90">{typeCounts[0]?.[0] || "—"}</div>
            <div className="text-[10px] text-muted-foreground/70">{typeCounts[0]?.[1] || 0} entities</div>
          </div>
          <div className="rounded border border-border/30 p-3">
            <div className="text-[9px] tracking-[2px] text-muted-foreground/70 uppercase mb-1">Most Referenced</div>
            <div className="text-lg font-light text-foreground/90 truncate">{topEntities[0]?.canonical_name || "—"}</div>
            <div className="text-[10px] text-muted-foreground/70">{topEntities[0]?.source_count || 0} docs</div>
          </div>
        </div>

        <div className="rounded border border-border/30 p-3">
          <div className="text-[9px] tracking-[2px] text-muted-foreground/70 uppercase mb-3">By Type</div>
          <div className="space-y-1.5">
            {typeCounts.map(([type, count]) => {
              const pct = allEntities.length > 0 ? (count / allEntities.length) * 100 : 0;
              const isActive = typeFilter === type;
              const color = TYPE_COLORS[type] || "#8A8A8A";
              return (
                <button key={type} onClick={() => setTypeFilter(isActive ? "" : type)} className="w-full flex items-center gap-2 group">
                  <span className="w-2 h-2 rounded-full shrink-0" style={{ background: color, opacity: isActive ? 1 : 0.6 }} />
                  <span className={`text-[11px] w-28 text-left truncate transition-colors ${isActive ? "text-foreground" : "text-muted-foreground/70 group-hover:text-muted-foreground"}`}>{type}</span>
                  <div className="flex-1 h-3 bg-card/30 rounded-sm overflow-hidden">
                    <div className="h-full rounded-sm transition-all" style={{ width: `${pct}%`, background: color, opacity: isActive ? 0.5 : 0.2 }} />
                  </div>
                  <span className={`text-[10px] w-8 text-right shrink-0 ${isActive ? "text-foreground/80" : "text-muted-foreground/70"}`}>{count}</span>
                </button>
              );
            })}
          </div>
        </div>

        <div className="rounded border border-border/30 p-3">
          <div className="text-[9px] tracking-[2px] text-muted-foreground/70 uppercase mb-2">Top Entities by References</div>
          <div className="flex gap-3 flex-wrap">
            {topEntities.map((e) => (
              <a
                key={e.id}
                href={`/n/${noosphereId}/entities/${e.id}`}
                className="flex items-center gap-1.5 px-2 py-1 rounded border border-border/20 hover:border-border/50 transition-colors"
              >
                <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: TYPE_COLORS[e.type] || "#8A8A8A" }} />
                <span className="text-[11px] text-foreground/80">{e.canonical_name}</span>
                <span className="text-[9px] text-muted-foreground/70">{e.source_count}</span>
              </a>
            ))}
          </div>
        </div>
      </div>

      <div className="space-y-3">
        <div className="flex items-center gap-3">
          <input
            type="text"
            value={searchFilter}
            onChange={(e) => setSearchFilter(e.target.value)}
            placeholder="Search entities"
            aria-label="Search entities by name"
            className="flex-1 bg-card/30 border border-border/30 rounded px-3 py-1.5 text-xs text-foreground/90 placeholder:text-muted-foreground/70 outline-none focus:border-border/60"
          />
          <select
            aria-label="Filter entities by type"
            className="bg-card border border-border/30 rounded px-3 py-1.5 text-xs text-muted-foreground"
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
          >
            <option value="">All types ({allEntities.length})</option>
            {typeCounts.map(([t, c]) => (
              <option key={t} value={t}>{t} ({c})</option>
            ))}
          </select>
          {(typeFilter || searchFilter) && (
            <button onClick={() => { setTypeFilter(""); setSearchFilter(""); }} className="text-[10px] text-muted-foreground/70 hover:text-muted-foreground transition-colors">
              clear
            </button>
          )}
        </div>
        <div className="text-[10px] text-muted-foreground/70">Showing {entities.length} of {allEntities.length}</div>
        <EntityTable entities={entities} />
      </div>
    </div>
  );
}
