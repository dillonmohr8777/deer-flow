import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuth } from "@/core/auth/AuthProvider";
import { useWorkspaceSelection } from "@/core/workspaces/hooks";

import { isStaticWebsiteOnly } from "../static-mode";

import {
  REPORTS_QUERY_KEY,
  createReviewDoc,
  getReportSummary,
  listReportConnectors,
  listReportLeads,
  listReviewDocs,
  updateReviewDoc,
} from "./api";
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

function useReportsScope() {
  const { user } = useAuth();
  const { data: workspaceData } = useWorkspaceSelection();
  return {
    userId: user?.id ?? null,
    workspaceId: workspaceData?.active_workspace_id ?? null,
  };
}

export function useReportSummary(period: ReportingPeriod) {
  const { userId, workspaceId } = useReportsScope();
  return useQuery<ReportSummary>({
    queryKey: [...REPORTS_QUERY_KEY, "summary", userId, workspaceId, period],
    queryFn: ({ signal }) => getReportSummary(period, workspaceId, signal),
    enabled: !isStaticWebsiteOnly(),
  });
}

export function useReportLeads(params: {
  period: ReportingPeriod;
  leadType?: LeadCategory;
  matchStatus?: MatchStatus;
}) {
  const { userId, workspaceId } = useReportsScope();
  return useQuery<ReportLeadsResponse>({
    queryKey: [
      ...REPORTS_QUERY_KEY,
      "leads",
      userId,
      workspaceId,
      params.period,
      params.leadType ?? null,
      params.matchStatus ?? null,
    ],
    queryFn: ({ signal }) =>
      listReportLeads({
        period: params.period,
        leadType: params.leadType,
        matchStatus: params.matchStatus,
        workspaceId,
        signal,
      }),
    enabled: !isStaticWebsiteOnly(),
  });
}

export function useReportConnectors() {
  const { userId, workspaceId } = useReportsScope();
  return useQuery<ReportConnectorsResponse>({
    queryKey: [...REPORTS_QUERY_KEY, "connectors", userId, workspaceId],
    queryFn: ({ signal }) => listReportConnectors(workspaceId, signal),
    enabled: !isStaticWebsiteOnly(),
  });
}

export function useReviewDocs(
  period?: ReportingPeriod,
  status?: ReviewDocStatus,
) {
  const { userId, workspaceId } = useReportsScope();
  return useQuery<ReviewDocListResponse>({
    queryKey: [
      ...REPORTS_QUERY_KEY,
      "review-docs",
      userId,
      workspaceId,
      period ?? null,
      status ?? null,
    ],
    queryFn: ({ signal }) =>
      listReviewDocs({ period, status, workspaceId, signal }),
    enabled: !isStaticWebsiteOnly(),
  });
}

export function useCreateReviewDoc() {
  const queryClient = useQueryClient();
  const { workspaceId } = useReportsScope();
  return useMutation<ReviewDoc, Error, CreateReviewDocInput>({
    mutationFn: (input) => createReviewDoc(input, workspaceId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: REPORTS_QUERY_KEY }),
  });
}

export function useUpdateReviewDoc() {
  const queryClient = useQueryClient();
  const { workspaceId } = useReportsScope();
  return useMutation<
    ReviewDoc,
    Error,
    { docId: string; input: UpdateReviewDocInput }
  >({
    mutationFn: ({ docId, input }) =>
      updateReviewDoc(docId, input, workspaceId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: REPORTS_QUERY_KEY }),
  });
}
