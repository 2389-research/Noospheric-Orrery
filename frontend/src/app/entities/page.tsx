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
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Entities</h1>
      <div className="flex gap-4">
        <select className="border rounded px-3 py-2 text-sm" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
          <option value="">All types</option>
          {types.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>
      <EntityTable entities={entities} />
    </div>
  );
}
