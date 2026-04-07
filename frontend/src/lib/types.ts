export interface DocumentSummary {
  id: string;
  title: string;
  status: "pending" | "classified" | "extracted" | "enriched";
  created_at: string;
  domains: string[];
  entity_count: number;
  content_type?: "text" | "image";
  thumbnail_path?: string;
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

export interface CriterionDetail {
  criterion: string;
  score: number;
  seed_score: number;
  evidence: string;
  improve: string;
}

export interface SimmerIteration {
  phase: string;
  iteration: number;
  scores: Record<string, number>;
  composite: number;
  key_change: string;
  asi: string;
  judge_mode: string;
  regressed: boolean;
  created_at: string;
  criterion_details: CriterionDetail[];
}

export interface SimmerJobDetail {
  job_id: string;
  job_type: string;
  target: string;
  status: string;
  phases: Record<string, SimmerIteration[]>;
  total_iterations: number;
}

export interface BatchResults {
  entities_found: number;
  entities_new: number;
  entities_matched: number;
  docs_processed: number;
  spec_version: string;
}

export interface EntityWithNew extends EntitySummary {
  is_new?: boolean;
}
