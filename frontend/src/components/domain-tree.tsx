"use client";

import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { DomainInfo } from "@/lib/types";
import { api } from "@/lib/api";

const PAGE_SIZE = 8;

export function DomainTree({ domains }: { domains: DomainInfo[] }) {
  const [page, setPage] = useState(0);

  if (domains.length === 0) return <p className="text-muted-foreground/50 text-xs">No domains yet</p>;

  const totalPages = Math.ceil(domains.length / PAGE_SIZE);
  const visible = domains.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const handleSimmer = async (path: string) => {
    try { await api.triggerDomainSimmer(path); } catch (e) { console.error(e); }
  };

  return (
    <div className="space-y-2">
      <div className="rounded border border-border/30">
        <div className="grid grid-cols-[1fr_60px_80px_70px] gap-2 px-3 py-1.5 border-b border-border/20 text-[9px] tracking-[2px] text-muted-foreground/50 uppercase">
          <span>Path</span><span>Docs</span><span>Spec</span><span></span>
        </div>
        {visible.map((d) => {
          const depth = d.path.split("/").length - 2;
          return (
            <div key={d.id} className="grid grid-cols-[1fr_60px_80px_70px] gap-2 px-3 py-1.5 border-b border-border/10 last:border-0 text-xs hover:bg-card/50 transition-colors">
              <span className="text-foreground/80" style={{ paddingLeft: `${depth * 12}px` }}>
                {depth > 0 && <span className="text-muted-foreground/30 mr-1">└</span>}
                {d.path.split("/").pop()}
              </span>
              <span className="text-muted-foreground/60">{d.document_count}</span>
              <Badge
                variant="outline"
                className={`w-fit text-[10px] ${d.spec_version ? "border-emerald-500/40 text-emerald-400" : "border-muted-foreground/20 text-muted-foreground/40"}`}
              >
                {d.spec_version ? `v${d.spec_version}` : "—"}
              </Badge>
              {d.spec_version ? (
                <Link
                  href={`/simmer/${d.id}`}
                  className="text-[10px] text-purple-400/70 hover:text-purple-400 transition-colors"
                >
                  view run
                </Link>
              ) : (
                <Button size="sm" variant="outline" className="h-5 text-[10px] px-2" onClick={() => handleSimmer(d.path)}>
                  simmer
                </Button>
              )}
            </div>
          );
        })}
      </div>
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-xs text-muted-foreground/50">
          <span>{domains.length} domains</span>
          <div className="flex gap-1">
            <Button size="sm" variant="ghost" className="h-6 text-[10px] px-2" disabled={page === 0} onClick={() => setPage(p => p - 1)}>←</Button>
            <span className="px-2 py-1">{page + 1}/{totalPages}</span>
            <Button size="sm" variant="ghost" className="h-6 text-[10px] px-2" disabled={page >= totalPages - 1} onClick={() => setPage(p => p + 1)}>→</Button>
          </div>
        </div>
      )}
    </div>
  );
}
