"use client";
import { Badge } from "@/components/ui/badge";
import { IngestResult } from "@/lib/types";
import { useNoosphereId } from "@/lib/hooks/use-noosphere-id";

interface UploadStatusProps { results: IngestResult[]; errors: string[]; }

export function UploadStatus({ results, errors }: UploadStatusProps) {
  const noosphereId = useNoosphereId();
  if (results.length === 0 && errors.length === 0) return null;
  const totalEntities = results.reduce((sum, r) => sum + r.entity_count, 0);
  const allDomains = [...new Set(results.flatMap((r) => r.domains))];
  const hasJobs = results.some((r) => r.jobs_queued.length > 0);

  return (
    <div className="space-y-4">
      {results.length > 0 && (
        <div className="rounded-lg border p-4">
          <p className="font-medium">{results.length} file{results.length !== 1 ? "s" : ""} uploaded
            {allDomains.length > 0 && `, ${allDomains.length} domain${allDomains.length !== 1 ? "s" : ""} detected`}
            {totalEntities > 0 && `, ${totalEntities} entities extracted`}</p>
          {hasJobs && <p className="text-sm text-muted-foreground mt-1">Simmering job queued — check <a href={`/n/${noosphereId}/pipeline`} className="underline">Pipeline</a> for progress</p>}
          <div className="mt-3 space-y-1">
            {results.map((r) => (
              <div key={r.document_id} className="flex items-center gap-2 text-sm">
                <Badge variant={r.entity_count > 0 ? "default" : "secondary"}>{r.entity_count > 0 ? "extracted" : "classified"}</Badge>
                <span>{r.title}</span>
                <span className="text-muted-foreground">→ {r.domains.join(", ") || "no domain"}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {errors.map((err, i) => <div key={i} className="rounded-lg border border-destructive p-4 text-sm text-destructive">{err}</div>)}
    </div>
  );
}
