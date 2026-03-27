"use client";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { StatsBar } from "@/components/stats-bar";
import { DomainTree } from "@/components/domain-tree";
import { JobsTable } from "@/components/jobs-table";
import { NormalizationPanel } from "@/components/normalization-panel";
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
    <div className="space-y-8">
      <h1 className="text-2xl font-semibold">Pipeline</h1>
      <StatsBar stats={stats} />
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-medium">Domains</h2>
          <Button onClick={async () => { try { await api.triggerGeneralSimmer(); refresh(); } catch (e) { console.error(e); } }}>
            Simmer General Spec
          </Button>
        </div>
        <DomainTree domains={domains} />
      </section>
      <section>
        <NormalizationPanel />
      </section>
      <section>
        <h2 className="text-lg font-medium mb-4">Jobs</h2>
        <JobsTable jobs={jobs} />
      </section>
    </div>
  );
}
