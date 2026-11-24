import type { StatusTone } from "@/components/workspace/page-body";
import type {
  ConnectorKey,
  ConnectorStatus,
  DataState,
  LeadCategory,
  MatchConfidence,
  MatchStatus,
  ReportingPeriod,
  ReviewDocStatus,
} from "@/core/reports/types";

export const PERIOD_OPTIONS: readonly {
  value: ReportingPeriod;
  label: string;
}[] = [
  { value: "last_7d", label: "Last 7d" },
  { value: "last_30d", label: "Last 30d" },
  { value: "this_month", label: "This Month" },
  { value: "last_month", label: "Last Month" },
];

export const LEAD_TYPE_OPTIONS: readonly {
  value: LeadCategory | "all";
  label: string;
}[] = [
  { value: "all", label: "All leads" },
  { value: "form", label: "Forms" },
  { value: "call", label: "Calls" },
  { value: "appointment", label: "Appointments" },
];

export const MATCH_STATUS_OPTIONS: readonly {
  value: MatchStatus | "all";
  label: string;
}[] = [
  { value: "all", label: "All match states" },
  { value: "matched", label: "Matched" },
  { value: "unmatched", label: "Unmatched" },
  { value: "pending_verification", label: "Pending verification" },
];

export const PERIOD_LABEL: Record<ReportingPeriod, string> = {
  last_7d: "Last 7d",
  last_30d: "Last 30d",
  this_month: "This Month",
  last_month: "Last Month",
};

export const LEAD_CATEGORY_LABEL: Record<LeadCategory, string> = {
  form: "Form",
  call: "Call",
  appointment: "Appointment",
};

export const CONNECTOR_LABEL: Record<ConnectorKey, string> = {
  google_ads: "Google Ads",
  ga4: "Google Analytics 4",
  gsc_bigquery: "GSC BigQuery",
  meta_ads: "Meta Ads",
  whatconverts: "WhatConverts",
  google_sheets: "Google Sheets",
};

export const CONFIDENCE_LABEL: Record<MatchConfidence, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
  unverified: "Unverified",
};

export function connectorStatusMeta(status: ConnectorStatus): {
  label: string;
  tone: StatusTone;
} {
  switch (status) {
    case "connected":
      return { label: "Connected", tone: "ok" };
    case "stale":
      return { label: "Stale", tone: "attention" };
    case "pending":
      return { label: "Pending", tone: "idle" };
    case "unavailable":
      return { label: "Unavailable", tone: "danger" };
  }
}

export function dataStateMeta(state: DataState): {
  label: string;
  tone: StatusTone;
} {
  switch (state) {
    case "verified":
      return { label: "Verified feeds", tone: "ok" };
    case "partial":
      return { label: "Partial coverage", tone: "attention" };
    case "pending":
      return { label: "Feeds pending", tone: "idle" };
    case "unavailable":
      return { label: "Feeds unavailable", tone: "danger" };
  }
}

export function matchStatusMeta(status: MatchStatus): {
  label: string;
  tone: StatusTone;
} {
  switch (status) {
    case "matched":
      return { label: "Matched", tone: "ok" };
    case "unmatched":
      return { label: "Unmatched", tone: "danger" };
    case "pending_verification":
      return { label: "Pending verification", tone: "attention" };
  }
}

export function reviewStatusMeta(status: ReviewDocStatus): {
  label: string;
  tone: StatusTone;
} {
  switch (status) {
    case "pending_review":
      return { label: "Pending review", tone: "attention" };
    case "approved":
      return { label: "Approved", tone: "ok" };
    case "needs_edits":
      return { label: "Needs edits", tone: "danger" };
  }
}

/**
 * Format an integer KPI count without ever substituting 0 for pending or
 * unavailable feeds.
 */
export function formatLeadCount(
  value: number | null | undefined,
  dataState: DataState,
): string {
  if (typeof value === "number" && Number.isInteger(value) && value >= 0) {
    return value.toLocaleString("en-US");
  }
  return dataState === "unavailable" ? "Unavailable" : "Pending";
}

export function formatIsoDate(
  iso: string | null | undefined,
  fallback = "Not recorded",
): string {
  if (!iso) return fallback;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return fallback;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

export function formatIsoDateTime(
  iso: string | null | undefined,
  fallback = "Not synced yet",
): string {
  if (!iso) return fallback;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return fallback;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

const ALLOWED_DOC_HOSTS = new Set(["docs.google.com", "drive.google.com"]);

/** Validate Google Doc / Drive URL client-side to match the backend gate. */
export function validateGoogleDocUrlClient(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) {
    return "Enter a Google Doc URL starting with https://docs.google.com/.";
  }
  if (/\s/.test(trimmed)) {
    return "Remove spaces from the Google Doc URL.";
  }
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return "Enter a valid HTTPS link to docs.google.com or drive.google.com.";
  }
  if (parsed.protocol !== "https:") {
    return "Google Doc links must start with https://.";
  }
  if (parsed.username || parsed.password) {
    return "Google Doc links must not include embedded credentials.";
  }
  if (!ALLOWED_DOC_HOSTS.has(parsed.hostname.toLowerCase())) {
    return "Link must point to docs.google.com or drive.google.com.";
  }
  if (!parsed.pathname || parsed.pathname === "/") {
    return "Include the full Google Doc link path.";
  }
  return null;
}
