"use client";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { StatsBar } from "@/components/stats-bar";
import { DomainTree } from "@/components/domain-tree";
import { JobsTable } from "@/components/jobs-table";
import { NormalizationPanel } from "@/components/normalization-panel";
import { PipelineStages } from "@/components/pipeline-stages";
import { api } from "@/lib/api";
import type { Stats, DomainInfo, JobInfo } from "@/lib/types";

export default function PipelinePage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [domains, setDomains] = useState<DomainInfo[]>([]);
  const [jobs, setJobs] = useState<JobInfo[]>([]);

  const refresh = async () => {
    const [s, d, j] = await Promise.all([api.getStats(), api.getDomains(), api.getJobs()]);
    setStats(s); setDomains(d); setJobs(j);
  };

  useEffect(() => { refresh(); const interval = setInterval(refresh, 5000); return () => clearInterval(interval); }, []);

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      <div className="flex items-center justify-between">
        <h1 className="text-sm tracking-[4px] text-muted-foreground uppercase">Pipeline</h1>
        <Button
          size="sm"
          variant="outline"
          className="text-xs tracking-wider"
          onClick={async () => { try { await api.triggerGeneralSimmer(); refresh(); } catch (e) { console.error(e); } }}
        >
          Simmer General Spec
        </Button>
      </div>

      <PipelineStages stats={stats} jobs={jobs} />

      <StatsBar stats={stats} />

      <section>
        <h2 className="text-xs tracking-[3px] text-muted-foreground uppercase mb-4">Domains</h2>
        <DomainTree domains={domains} />
      </section>

      <section>
        <NormalizationPanel />
      </section>

      <section>
        <h2 className="text-xs tracking-[3px] text-muted-foreground uppercase mb-4">Jobs</h2>
        <JobsTable jobs={jobs} />
      </section>
    </div>
  );
}
