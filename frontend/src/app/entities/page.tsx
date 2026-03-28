"use client";
import { useEffect, useState } from "react";
import { EntityTable } from "@/components/entity-table";
import { api } from "@/lib/api";
import type { EntitySummary } from "@/lib/types";

export default function EntitiesPage() {
  const [entities, setEntities] = useState<EntitySummary[]>([]);
  const [typeFilter, setTypeFilter] = useState("");

  useEffect(() => {
    api.getEntities(typeFilter ? { type: typeFilter } : undefined).then(setEntities);
  }, [typeFilter]);

  const types = [...new Set(entities.map((e) => e.type))].sort();

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-sm tracking-[4px] text-muted-foreground uppercase">Entities</h1>
        <select
          className="bg-card border border-border/30 rounded px-3 py-1.5 text-xs text-muted-foreground"
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
        >
          <option value="">All types</option>
          {types.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>
      <EntityTable entities={entities} />
    </div>
  );
}
