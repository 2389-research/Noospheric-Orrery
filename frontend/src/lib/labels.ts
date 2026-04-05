/**
 * Human-readable labels for internal identifiers.
 * Keeps raw identifiers out of the UI.
 */

const JOB_TYPE_LABELS: Record<string, string> = {
  simmer_general: "General Spec Refinement",
  simmer_domain: "Domain Spec Refinement",
  simmer_golden_set: "Golden Set Refinement",
  simmer_extraction_spec: "Extraction Spec Refinement",
  simmer_domain_golden_set: "Domain Golden Set",
  simmer_domain_extraction_spec: "Domain Extraction Spec",
  extract_batch: "Batch Extraction",
  post_process: "Post-Processing",
};

export function jobTypeLabel(type: string): string {
  return JOB_TYPE_LABELS[type] || type.replace(/_/g, " ");
}

export function timeSince(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const utcStr = dateStr.includes("Z") || dateStr.includes("+") ? dateStr : dateStr + "Z";
  const seconds = Math.floor((Date.now() - new Date(utcStr).getTime()) / 1000);
  if (seconds < 0) return "just now";
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}
