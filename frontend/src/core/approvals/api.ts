import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { Approval, ApprovalEdit, ApprovalStatus } from "./types";

export const APPROVALS_QUERY_KEY = ["approvals"] as const;

async function readError(response: Response, fallback: string) {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail) return body.detail;
  } catch {
    // Fall through to the caller-provided message.
  }
  return fallback;
}

async function send(path: string, init: RequestInit, fallback: string) {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/approvals${path}`,
    init,
  );
  if (!response.ok) throw new Error(await readError(response, fallback));
  return response;
}

/** ``GET /api/approvals`` -- the caller's inbox, newest first. */
export async function listApprovals(
  status?: ApprovalStatus,
): Promise<Approval[]> {
  const response = await send(
    status ? `?status=${status}` : "",
    { method: "GET" },
    "Failed to load approvals.",
  );
  return ((await response.json()) as { approvals: Approval[] }).approvals;
}

/** ``PATCH /api/approvals/{id}`` -- edit a still-pending action. */
export async function editApproval(
  id: string,
  edit: ApprovalEdit,
): Promise<Approval> {
  const response = await send(
    `/${id}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(edit),
    },
    "Failed to save changes.",
  );
  return (await response.json()) as Approval;
}

/** ``POST /api/approvals/{id}/approve`` -- releases the action to its executor. */
export async function approveApproval(id: string): Promise<Approval> {
  const response = await send(
    `/${id}/approve`,
    { method: "POST" },
    "Failed to approve.",
  );
  return (await response.json()) as Approval;
}

/** ``POST /api/approvals/{id}/reject`` -- the action is never executed. */
export async function rejectApproval(id: string): Promise<Approval> {
  const response = await send(
    `/${id}/reject`,
    { method: "POST" },
    "Failed to reject.",
  );
  return (await response.json()) as Approval;
}
