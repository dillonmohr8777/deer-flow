export type ReportingPeriod =
  | "last_7d"
  | "last_30d"
  | "this_month"
  | "last_month";

export type ConnectorKey =
  | "google_ads"
  | "ga4"
  | "gsc_bigquery"
  | "meta_ads"
  | "whatconverts"
  | "google_sheets";

export type ConnectorStatus = "connected" | "stale" | "pending" | "unavailable";

export type LeadCategory = "form" | "call" | "appointment";

export type MatchStatus = "matched" | "unmatched" | "pending_verification";

export type MatchConfidence = "high" | "medium" | "low" | "unverified";

export type ReviewDocStatus = "pending_review" | "approved" | "needs_edits";

export type DataState = "verified" | "partial" | "pending" | "unavailable";

export interface LeadKpiSummary {
  total_leads: number | null;
  forms: number | null;
  calls: number | null;
  appointments: number | null;
  appointment_label: string;
  matched_leads: number | null;
  data_state: DataState;
  connected_lead_sources: string[];
  pending_lead_sources: string[];
  unavailable_lead_sources: string[];
  excluded_non_lead_signals: string[];
}

export interface ConnectorsSummary {
  connected: number;
  stale: number;
  pending: number;
  unavailable: number;
}

export interface ReviewDocsSummary {
  total: number;
  pending_review: number;
  approved: number;
  needs_edits: number;
}

export interface ReportSummary {
  workspace_id: string;
  workspace_name: string | null;
  period: ReportingPeriod;
  window_start: string;
  window_end: string;
  kpis: LeadKpiSummary;
  connectors_summary: ConnectorsSummary;
  review_docs_summary: ReviewDocsSummary;
}

export interface LeadRecord {
  id: string;
  workspace_id: string;
  lead_name: string;
  lead_type: LeadCategory;
  channel: string;
  source_connector: ConnectorKey;
  campaign_name: string;
  external_lead_id: string | null;
  match_status: MatchStatus;
  match_confidence: MatchConfidence;
  occurred_at: string;
  notes: string;
  created_at: string;
}

export interface ReportLeadsResponse {
  workspace_id: string;
  period: ReportingPeriod;
  data_state: DataState;
  total_count: number;
  leads: LeadRecord[];
}

export interface ConnectorHealth {
  connector_key: ConnectorKey;
  display_name: string;
  status: ConnectorStatus;
  provides_leads: boolean;
  capability_summary: string;
  external_account_ref: string | null;
  last_synced_at: string | null;
  detail: string;
  required_credential_refs: string[];
}

export interface ReportConnectorsResponse {
  workspace_id: string;
  connectors: ConnectorHealth[];
}

export interface ReviewDocComment {
  id: string;
  author_id: string;
  author_label: string;
  body: string;
  created_at: string;
}

export interface ReviewDoc {
  id: string;
  workspace_id: string;
  title: string;
  doc_url: string;
  period_key: ReportingPeriod;
  status: ReviewDocStatus;
  created_by: string;
  decided_by: string | null;
  decided_at: string | null;
  comments: ReviewDocComment[];
  created_at: string;
  updated_at: string;
}

export interface ReviewDocListResponse {
  workspace_id: string;
  review_docs: ReviewDoc[];
}

export interface CreateReviewDocInput {
  title: string;
  doc_url: string;
  period_key: ReportingPeriod;
}

export interface UpdateReviewDocInput {
  status?: ReviewDocStatus;
  comment?: string;
}
