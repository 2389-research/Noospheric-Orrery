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

export interface DocumentDetail {
  id: string;
  title: string;
  source_path: string | null;
  content: string;
  content_type?: "text" | "image";
  thumbnail_path?: string | null;
  status: string;
  created_at: string;
  domains: { path: string; is_primary: boolean; confidence: number }[];
  entities: { id: string; canonical_name: string; type: string }[];
}

export interface DomainInfo {
  id: string;
  path: string;
  parent_path: string | null;
  document_count: number;
  text_count: number;
  image_count: number;
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
  image_count: number;
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

export type CorrectionAction = "invalidate" | "merge" | "retype" | "rename";
export type JudgeVerdict = "accept" | "reject" | "defer";

export interface Correction {
  id: string;
  action: CorrectionAction;
  target_entity_id: string;
  target_entity_name: string;
  target_b_entity_id: string | null;
  target_b_name: string | null;
  proposed_type: string | null;
  proposed_name: string | null;
  rationale: string | null;
  proposer: string | null;
  status: string;
  judge_verdict: JudgeVerdict | null;
  judge_confidence: number | null;
  judge_rationale: string | null;
  reviewer: string | null;
  created_at: string;
  resolved_at: string | null;
}

// ── Collections ─────────────────────────────────────────────────────────────
// The API contract for a collection, defined once here rather than restated as
// structural literals in api.ts and in the panel component — three copies of the
// same shape drift silently, and the panel's copy is what the response is checked
// against.

export interface CollectionTopEntity {
  id: string;
  name: string;
  type: string;
  count: number;
}

/** A collection node's identity, as carried on the viz `node_selected` payload. */
export interface CollectionPanelData {
  id: string;
  name: string;
  document_count: number;
  domain?: string | null;
}

/** GET /collections/{id}/summary */
export interface CollectionSummaryResponse {
  collection: {
    id: string;
    name: string;
    kind: string;
    domain: string | null;
    document_count: number;
  };
  summary: string;
  top_entities: CollectionTopEntity[];
}
