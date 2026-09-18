export type TargetType = "person" | "organization" | "company" | "domain";

export type ResearchStatus =
  | "NOT_STARTED"
  | "ACTIVITY_RECORDED"
  | "REQUESTED"
  | "ENQUEUED"
  | "RUNNING"
  | "COMPLETED"
  | "FAILED";

export type ClaimStatus =
  | "SUPPORTED"
  | "PARTIALLY_SUPPORTED"
  | "CONTRADICTED"
  | "INSUFFICIENT_EVIDENCE"
  | "UNVERIFIED_LEAD";

export type EvidenceRelation = "supports" | "contradicts" | "context";

export type TargetInput = {
  type: TargetType;
  name: string;
  birth_date?: string | null;
  birth_year?: number | null;
  place?: string | null;
  known_orgnrs: string[];
  known_organizations: string[];
};

export type ModuleStatus = "NOT_STARTED" | "IN_PROGRESS" | "COMPLETE" | "PARTIAL" | "BLOCKED";

export type ModuleState = {
  module: string;
  enabled: boolean;
  status: ModuleStatus;
  coverage: {
    providers?: string[];
    query_classes?: string[];
    query_count?: number;
    document_count?: number;
    gaps?: string[];
    unavailable_sources?: string[];
  };
  stop_reason: string | null;
};

export type ResearchSummary = {
  executed: number;
  blocked: number;
  failed: number;
  stopped_reason: string;
};

export type ResearchState = {
  status: ResearchStatus;
  job_id: string | null;
  requested_at: string | null;
  enqueued_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  summary: ResearchSummary | null;
  error_code: string | null;
  legacy_activity: boolean;
};

export type LeadState = {
  id: string;
  lead_type: string;
  value: unknown;
  reason: string;
  originating_claim_id: string | null;
  priority: number;
  depth: number;
  status: string;
  scope_area: string | null;
  trigger_type: string | null;
  information_need: string | null;
  relation_depth: number;
  blocked_reason: string | null;
  created_at: string;
};

export type EvidenceState = {
  evidence_id: string;
  relation: EvidenceRelation;
  document_id: string;
  original_url: string | null;
  canonical_url: string | null;
  source_id: string | null;
  source_name: string | null;
  fetched_at: string | null;
  sha256: string | null;
  raw_storage_key: string | null;
  locator_type: string;
  locator: Record<string, unknown>;
  excerpt: string | null;
  structured_value: unknown;
};

export type ClaimState = {
  id: string;
  subject_entity_id: string | null;
  predicate: string;
  value: unknown;
  status: ClaimStatus;
  created_at: string;
  evidence: EvidenceState[];
};

export type EntityState = {
  id: string;
  schema: string;
  canonical_name: string | null;
  attributes: Record<string, unknown>;
  resolution_state: string;
  relation_depth: number;
  expansion_state: string;
  material_reason: string | null;
};

export type InvestigationDetail = {
  id: string;
  status: string;
  target: TargetInput;
  purpose: string;
  scope_modules: string[];
  expansion_policy: string;
  max_relation_depth: number;
  research: ResearchState;
  modules: ModuleState[];
  leads: LeadState[];
  claims: ClaimState[];
  entities: EntityState[];
  document_count: number;
  evidence_count: number;
};

export function formatApiDetail(detail: unknown): string {
  if (Array.isArray(detail)) {
    const text = detail
      .map((item) => (typeof item === "string" ? item : (item as { msg?: string } | null)?.msg))
      .filter(Boolean)
      .join(" ");
    if (text) return text;
  }
  if (typeof detail === "string") return detail;
  if (detail === null || detail === undefined) return "";
  try {
    return JSON.stringify(detail);
  } catch {
    return "";
  }
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "Ikke registrert";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("nb-NO");
}

export function safeHttpUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}
