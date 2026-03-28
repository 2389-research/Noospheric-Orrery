export interface DocumentSummary {
  id: string;
  title: string;
  status: "pending" | "classified" | "extracted" | "enriched";
  created_at: string;
  domains: string[];
  entity_count: number;
}

export interface DomainInfo {
  id: string;
  path: string;
  parent_path: string | null;
  document_count: number;
  spec_version: number | null;
  created_at: string;
}

export interface EntitySummary {
  id: string;
  canonical_name: string;
  type: string;
  source_count: number;
}

export interface JobInfo {
  id: string;
  type: string;
  target: string;
  status: "queued" | "running" | "completed" | "failed";
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface Stats {
  document_count: number;
  entity_count: number;
  domain_count: number;
  active_jobs: number;
}

export interface IngestResult {
  document_id: string;
  title: string;
  domains: string[];
  entity_count: number;
  jobs_queued: string[];
}
