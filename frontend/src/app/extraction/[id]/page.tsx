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
import { ReaderPane } from "@/components/reader/reader-pane";

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
  const [docEntityIds, setDocEntityIds] = useState<Set<string> | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [jobData, docsData, entitiesData, normData] = await Promise.all([
        api.getJob(jobId),
        api.getDocuments(),
        api.getEntities({ job_id: jobId, limit: 500 }),
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

  // When a doc is selected, fetch its entities to filter
  useEffect(() => {
    if (!selectedDocId) {
      setDocEntityIds(null);
      return;
    }
    fetch(`/api/documents/${selectedDocId}`)
      .then((r) => r.json())
      .then((doc) => {
        const ids = new Set<string>(doc.entities?.map((e: { id: string }) => e.id) || []);
        setDocEntityIds(ids);
      })
      .catch(() => setDocEntityIds(null));
  }, [selectedDocId]);

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

  const typeSet = new Set(entities.map((e) => e.type));
  const typeNames = Array.from(typeSet).sort();

  // Filter entities by selected doc
  const panelEntities = docEntityIds
    ? entities.filter((e) => docEntityIds.has(e.id))
    : entities;

  const selectedDoc = docs.find((d) => d.id === selectedDocId);
  const selectedDocTitle = selectedDoc?.title ?? null;

  const entitiesNew = job.results?.entities_new ?? entities.filter((e) => e.is_new).length;

  const handleTypeClick = (type: string) => {
    setActiveTab((prev) => (prev === type ? "all" : type));
  };

  const handleDocSelect = (docId: string | null) => {
    setSelectedDocId((prev) => (prev === docId ? null : docId));
  };

  return (
    <div className="max-w-6xl mx-auto space-y-4">
      <ExtractionHeader job={job} />

      <StatStrip
        job={job}
        typeNames={typeNames}
        totalMerges={normSummary?.total_merges ?? 0}
        isRunning={isRunning}
      />

      <div className="flex gap-4" style={{ minHeight: "500px" }}>
        <div className="w-[220px] shrink-0">
          <DocList
            docs={docs}
            selectedDocId={selectedDocId}
            onSelectDoc={handleDocSelect}
            isRunning={isRunning}
          />
        </div>

        <div className="flex-1 min-w-0">
          {selectedDocId ? (
            <ReaderPane
              documentId={selectedDocId}
              onClose={() => setSelectedDocId(null)}
            />
          ) : (
            <div className="space-y-4">
              <EntityPanel
                entities={panelEntities}
                activeTab={activeTab}
                onTabChange={setActiveTab}
                entitiesNew={entitiesNew}
                selectedDocTitle={selectedDocTitle}
                isFailed={isFailed}
              />

              <div className="grid grid-cols-2 gap-4">
                <TypeDistribution
                  entities={entities}
                  activeType={activeTab === "all" || activeTab === "new" ? null : activeTab}
                  onTypeClick={handleTypeClick}
                />
                <NormalizationSummary data={normSummary} />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
