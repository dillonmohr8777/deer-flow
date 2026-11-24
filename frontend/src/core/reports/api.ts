import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  CreateReviewDocInput,
  LeadCategory,
  MatchStatus,
  ReportConnectorsResponse,
  ReportingPeriod,
  ReportLeadsResponse,
  ReportSummary,
  ReviewDoc,
  ReviewDocListResponse,
  ReviewDocStatus,
  UpdateReviewDocInput,
} from "./types";

export const REPORTS_QUERY_KEY = ["reports"] as const;

async function readError(response: Response, fallback: string) {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail) return body.detail;
  } catch {
    // Fall through to the caller-provided fallback message.
  }
  return fallback;
}

async function send(
  path: string,
  init: RequestInit,
  fallback: string,
  workspaceId?: string | null,
) {
  const headers = new Headers(init.headers);
  if (workspaceId) {
    headers.set("X-Reports-Workspace", workspaceId);
  }
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/reports${path}`,
    {
      ...init,
      headers,
    },
  );
  if (!response.ok) {
    throw new Error(await readError(response, fallback));
  }
  return response;
}

export async function getReportSummary(
  period: ReportingPeriod,
  workspaceId?: string | null,
  signal?: AbortSignal,
): Promise<ReportSummary> {
  const params = new URLSearchParams({ period });
  const response = await send(
    `/summary?${params.toString()}`,
    { method: "GET", signal },
    "Could not load report summary.",
    workspaceId,
  );
  return (await response.json()) as ReportSummary;
}

export interface ListReportLeadsParams {
  period: ReportingPeriod;
  leadType?: LeadCategory;
  matchStatus?: MatchStatus;
  channel?: string;
  limit?: number;
  offset?: number;
  workspaceId?: string | null;
  signal?: AbortSignal;
}

export async function listReportLeads({
  period,
  leadType,
  matchStatus,
  channel,
  limit = 100,
  offset = 0,
  workspaceId,
  signal,
}: ListReportLeadsParams): Promise<ReportLeadsResponse> {
  const params = new URLSearchParams({
    period,
    limit: String(limit),
    offset: String(offset),
  });
  if (leadType) params.set("lead_type", leadType);
  if (matchStatus) params.set("match_status", matchStatus);
  if (channel) params.set("channel", channel);
  const response = await send(
    `/leads?${params.toString()}`,
    { method: "GET", signal },
    "Could not load verified leads.",
    workspaceId,
  );
  return (await response.json()) as ReportLeadsResponse;
}

export async function listReportConnectors(
  workspaceId?: string | null,
  signal?: AbortSignal,
): Promise<ReportConnectorsResponse> {
  const response = await send(
    "/connectors",
    { method: "GET", signal },
    "Could not load connector health.",
    workspaceId,
  );
  return (await response.json()) as ReportConnectorsResponse;
}

export async function listReviewDocs(params?: {
  period?: ReportingPeriod;
  status?: ReviewDocStatus;
  workspaceId?: string | null;
  signal?: AbortSignal;
}): Promise<ReviewDocListResponse> {
  const query = new URLSearchParams();
  if (params?.period) query.set("period", params.period);
  if (params?.status) query.set("status", params.status);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  const response = await send(
    `/review-docs${suffix}`,
    { method: "GET", signal: params?.signal },
    "Could not load review documents.",
    params?.workspaceId,
  );
  return (await response.json()) as ReviewDocListResponse;
}

export async function createReviewDoc(
  input: CreateReviewDocInput,
  workspaceId?: string | null,
): Promise<ReviewDoc> {
  const response = await send(
    "/review-docs",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
    "Could not attach Google Doc for review.",
    workspaceId,
  );
  return (await response.json()) as ReviewDoc;
}

export async function updateReviewDoc(
  docId: string,
  input: UpdateReviewDocInput,
  workspaceId?: string | null,
): Promise<ReviewDoc> {
  const response = await send(
    `/review-docs/${encodeURIComponent(docId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
    "Could not update review document.",
    workspaceId,
  );
  return (await response.json()) as ReviewDoc;
}
