"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import type { JobInfo, BatchResults, DocumentSummary, EntityWithNew } from "@/lib/types";
import { ExtractionHeader } from "@/components/extraction/extraction-header";
import { StatStrip } from "@/components/extraction/stat-strip";
import { DocList } from "@/components/extraction/doc-list";
import { EntityPanel } from "@/components/extraction/entity-panel";
import { TypeDistribution } from "@/components/extraction/type-distribution";
import { NormalizationSummary } from "@/components/extraction/normalization-summary";

type JobWithResults = JobInfo & { results?: BatchResults };

type NormSummary = {
  merges_by_method: Record<string, number>;
  total_merges: number;
  pending_reviews: number;
  recent_merges: { from: string; to: string; method: string; similarity: number; date: string }[];
};

export default function ExtractionPage() {
  const params = useParams();
  const jobId = params.id as string;

  const [job, setJob] = useState<JobWithResults | null>(null);
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [entities, setEntities] = useState<EntityWithNew[]>([]);
  const [normSummary, setNormSummary] = useState<NormSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  // UI state
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("all");

  const fetchData = useCallback(async () => {
    try {
      const [jobData, docsData, entitiesData, normData] = await Promise.all([
        api.getJob(jobId),
        api.getDocuments(),
        api.getEntities({ job_id: jobId }),
        api.getNormalizationSummary(),
      ]);

      setJob(jobData);
      setDocs(docsData);
      setEntities(entitiesData as EntityWithNew[]);
      setNormSummary(normData);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load extraction");
    }
  }, [jobId]);

  // Initial load
  useEffect(() => {
    fetchData();
  }, [jobId]);

  // Poll while running
  useEffect(() => {
    if (!job) return;
    if (job.status !== "running") return;
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [job, fetchData]);

  if (error) {
    return (
      <div className="max-w-6xl mx-auto py-12 text-center">
        <p className="text-red-400 text-sm">{error}</p>
      </div>
    );
  }

  if (!job) {
    return (
      <div className="max-w-6xl mx-auto py-12 text-center">
        <p className="text-muted-foreground/90 text-xs tracking-[2px] animate-pulse">loading…</p>
      </div>
    );
  }

  const isRunning = job.status === "running";
  const isFailed = job.status === "failed";

  // Derive distinct type names from entities
  const typeSet = new Set(entities.map((e) => e.type));
  const typeNames = Array.from(typeSet).sort();

  // Filter entities by selected doc
  // Since we don't have per-doc filtering in entities yet, we show all entities
  // (or rely on the job_id param to already scope them)
  const docFilteredEntities = entities;

  // Find selected doc title
  const selectedDoc = docs.find((d) => d.id === selectedDocId);
  const selectedDocTitle = selectedDoc?.title ?? null;

  // Entities shown: filtered by doc (if selected), then by tab in EntityPanel
  const panelEntities = selectedDocId
    ? docFilteredEntities // ideally filtered by doc; API may scope by job_id already
    : entities;

  const entitiesNew = job.results?.entities_new ?? entities.filter((e) => e.is_new).length;

  // Handle type click from TypeDistribution — sync to entity panel tab
  const handleTypeClick = (type: string) => {
    setActiveTab((prev) => (prev === type ? "all" : type));
  };

  return (
    <div className="max-w-6xl mx-auto space-y-4">
      {/* Header */}
      <ExtractionHeader job={job} />

      {/* Stat strip */}
      <StatStrip
        job={job}
        typeNames={typeNames}
        totalMerges={normSummary?.total_merges ?? 0}
        isRunning={isRunning}
      />

      {/* Main layout: doc list left + right pane */}
      <div className="flex gap-4" style={{ minHeight: "500px" }}>
        {/* Doc list — fixed width */}
        <div className="w-[220px] shrink-0">
          <DocList
            docs={docs}
            selectedDocId={selectedDocId}
            onSelectDoc={setSelectedDocId}
            isRunning={isRunning}
          />
        </div>

        {/* Right pane */}
        <div className="flex-1 min-w-0 space-y-4">
          {/* Entity panel */}
          <EntityPanel
            entities={panelEntities}
            activeTab={activeTab}
            onTabChange={setActiveTab}
            entitiesNew={entitiesNew}
            selectedDocTitle={selectedDocTitle}
            isFailed={isFailed}
          />

          {/* Bottom row */}
          <div className="grid grid-cols-2 gap-4">
            <TypeDistribution
              entities={entities}
              activeType={activeTab === "all" || activeTab === "new" ? null : activeTab}
              onTypeClick={handleTypeClick}
            />
            <NormalizationSummary data={normSummary} />
          </div>
        </div>
      </div>
    </div>
  );
}
