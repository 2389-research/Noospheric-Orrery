const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchAPI<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, options);
  if (!res.ok) throw new Error(`API error: ${res.status} ${await res.text()}`);
  return res.json();
}

export const api = {
  getStats: () => fetchAPI<import("./types").Stats>("/stats"),
  getDocuments: () => fetchAPI<import("./types").DocumentSummary[]>("/documents"),
  getDomains: () => fetchAPI<import("./types").DomainInfo[]>("/domains"),
  getEntities: (params?: { type?: string; domain?: string }) => {
    const query = new URLSearchParams();
    if (params?.type) query.set("type", params.type);
    if (params?.domain) query.set("domain", params.domain);
    return fetchAPI<import("./types").EntitySummary[]>(`/entities?${query}`);
  },
  getJobs: () => fetchAPI<import("./types").JobInfo[]>("/jobs"),
  ingestFile: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetchAPI<import("./types").IngestResult>("/ingest", { method: "POST", body: form });
  },
  ingestDirectory: (path: string) =>
    fetchAPI<{ documents: import("./types").IngestResult[]; total: number }>("/ingest/directory", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    }),
  getJobIterations: (jobId: string) => fetchAPI<import("./types").SimmerJobDetail>(`/jobs/${jobId}/iterations`),
  triggerGeneralSimmer: () => fetchAPI<{ job_id: string }>("/simmer/general", { method: "POST" }),
  triggerDomainSimmer: (domain: string) => fetchAPI<{ job_id: string }>(`/simmer/${domain}`, { method: "POST" }),
  triggerNormalization: () =>
    fetchAPI<{
      plural_merges: number;
      embedding_merges: number;
      queued_for_review: number;
      total_entities_before: number;
      total_entities_after: number;
    }>("/normalize", { method: "POST" }),
  getNormalizationSummary: () =>
    fetchAPI<{
      merges_by_method: Record<string, number>;
      total_merges: number;
      pending_reviews: number;
      recent_merges: { from: string; to: string; method: string; similarity: number; date: string }[];
    }>("/normalize/summary"),
  getReviewQueue: () =>
    fetchAPI<{ id: string; entity_a: string; entity_b: string; similarity: number }[]>("/normalize/review"),
  resolveReview: (reviewId: string, action: "merge" | "keep_separate") =>
    fetchAPI<{ status: string }>(`/normalize/review/${reviewId}?action=${action}`, { method: "POST" }),
};
