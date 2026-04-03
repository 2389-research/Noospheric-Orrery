"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { DomainInfo, JobInfo } from "@/lib/types";
import { api } from "@/lib/api";
import { useNoosphereId } from "@/lib/hooks/use-noosphere-id";

const PAGE_SIZE = 12;

type SortKey = "size" | "name" | "spec";

function SimmerAction({ domain: d, jobs, onSimmer }: { domain: DomainInfo; jobs: JobInfo[]; onSimmer: (path: string) => void }) {
  const noosphereId = useNoosphereId();
  const isRunning = jobs.some(j => j.type.startsWith("simmer") && j.target === d.path && (j.status === "running" || j.status === "queued"));
  const simmerJob = jobs.find(j => j.type.startsWith("simmer") && j.target === d.path);

  if (isRunning) {
    return <span className="text-[10px] text-purple-400/60 animate-pulse">simmering...</span>;
  }

  if (d.spec_version) {
    return (
      <span className="flex items-center gap-2">
        {simmerJob && (
          <Link href={`/n/${noosphereId}/simmer/${simmerJob.id}`} className="text-[10px] text-purple-400/70 hover:text-purple-400 transition-colors">
            v{d.spec_version}
          </Link>
        )}
        <button onClick={() => onSimmer(d.path)} className="text-[10px] text-muted-foreground/30 hover:text-purple-400/70 transition-colors">
          re-simmer
        </button>
      </span>
    );
  }

  return (
    <Button size="sm" variant="outline" className="h-5 text-[10px] px-2" onClick={() => onSimmer(d.path)}>
      simmer
    </Button>
  );
}

export function DomainTree({ domains, jobs = [] }: { domains: DomainInfo[]; jobs?: JobInfo[] }) {
  const [page, setPage] = useState(0);
  const [sortBy, setSortBy] = useState<SortKey>("size");
  const [filter, setFilter] = useState("");

  const filtered = useMemo(() => {
    let list = domains;
    if (filter.trim()) {
      const q = filter.toLowerCase();
      list = list.filter(d => d.path.toLowerCase().includes(q));
    }
    const sorted = [...list];
    if (sortBy === "size") {
      sorted.sort((a, b) => b.document_count - a.document_count);
    } else if (sortBy === "name") {
      sorted.sort((a, b) => a.path.localeCompare(b.path));
    } else if (sortBy === "spec") {
      sorted.sort((a, b) => (b.spec_version || 0) - (a.spec_version || 0));
    }
    return sorted;
  }, [domains, sortBy, filter]);

  if (domains.length === 0) return <p className="text-muted-foreground/85 text-xs">No domains yet</p>;

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const safePage = Math.min(page, Math.max(totalPages - 1, 0));
  const visible = filtered.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE);

  const handleSimmer = async (path: string) => {
    try { await api.triggerDomainSimmer(path); } catch (e) { console.error(e); }
  };

  return (
    <div className="space-y-2">
      {/* Filter + sort controls */}
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={filter}
          onChange={(e) => { setFilter(e.target.value); setPage(0); }}
          placeholder="filter domains..."
          className="flex-1 text-xs bg-card/30 border border-border/30 rounded px-2 py-1 text-foreground/90 placeholder:text-muted-foreground/50 outline-none focus:border-border/60"
        />
        <div className="flex gap-1">
          {(["size", "name", "spec"] as SortKey[]).map((key) => (
            <button
              key={key}
              onClick={() => { setSortBy(key); setPage(0); }}
              className={`text-[9px] tracking-wider uppercase px-2 py-0.5 rounded border transition-colors ${
                sortBy === key
                  ? "border-primary/50 text-primary bg-primary/10"
                  : "border-border/20 text-muted-foreground/60 hover:text-muted-foreground/90"
              }`}
            >
              {key}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded border border-border/30">
        <div className="grid grid-cols-[1fr_60px_80px_70px] gap-2 px-3 py-1.5 border-b border-border/20 text-[9px] tracking-[2px] text-muted-foreground/85 uppercase">
          <span>Path</span><span>Docs</span><span>Spec</span><span></span>
        </div>
        {visible.map((d) => {
          const depth = sortBy === "name" ? d.path.split("/").length - 2 : 0;
          return (
            <div key={d.id} className="grid grid-cols-[1fr_60px_80px_70px] gap-2 px-3 py-1.5 border-b border-border/10 last:border-0 text-xs hover:bg-card/50 transition-colors">
              <span className="text-foreground/90 truncate" style={{ paddingLeft: `${depth * 12}px` }}>
                {depth > 0 && <span className="text-muted-foreground/85 mr-1">└</span>}
                {sortBy === "name" ? d.path.split("/").pop() : d.path}
              </span>
              <span className="text-muted-foreground/90">{d.document_count}</span>
              <Badge
                variant="outline"
                className={`w-fit text-[10px] ${d.spec_version ? "border-emerald-500/40 text-emerald-400" : "border-muted-foreground/90 text-muted-foreground/90"}`}
              >
                {d.spec_version ? `v${d.spec_version}` : "—"}
              </Badge>
              <SimmerAction domain={d} jobs={jobs} onSimmer={handleSimmer} />
            </div>
          );
        })}
        {visible.length === 0 && (
          <div className="px-3 py-3 text-xs text-muted-foreground/50">No domains match &ldquo;{filter}&rdquo;</div>
        )}
      </div>
      <div className="flex items-center justify-between text-xs text-muted-foreground/85">
        <span>{filtered.length} domain{filtered.length !== 1 ? "s" : ""}</span>
        {totalPages > 1 && (
          <div className="flex gap-1">
            <Button size="sm" variant="ghost" className="h-6 text-[10px] px-2" disabled={safePage === 0} onClick={() => setPage(p => p - 1)}>←</Button>
            <span className="px-2 py-1">{safePage + 1}/{totalPages}</span>
            <Button size="sm" variant="ghost" className="h-6 text-[10px] px-2" disabled={safePage >= totalPages - 1} onClick={() => setPage(p => p + 1)}>→</Button>
          </div>
        )}
      </div>
    </div>
  );
}
