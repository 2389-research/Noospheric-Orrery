"use client";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { DomainInfo } from "@/lib/types";
import { api } from "@/lib/api";

export function DomainTree({ domains }: { domains: DomainInfo[] }) {
  if (domains.length === 0) return <p className="text-muted-foreground">No domains yet</p>;
  const handleSimmer = async (path: string) => { try { await api.triggerDomainSimmer(path); } catch (e) { console.error(e); } };
  return (
    <div className="space-y-1">
      {domains.map((d) => (
        <div key={d.id} className="flex items-center gap-3 py-1 px-2 rounded hover:bg-muted">
          <span className="font-mono text-sm flex-1">{d.path}</span>
          <span className="text-sm text-muted-foreground">{d.document_count} docs</span>
          <Badge variant={d.spec_version ? "default" : "outline"}>{d.spec_version ? `v${d.spec_version}` : "no spec"}</Badge>
          {!d.spec_version && <Button size="sm" variant="outline" onClick={() => handleSimmer(d.path)}>Simmer</Button>}
        </div>
      ))}
    </div>
  );
}
