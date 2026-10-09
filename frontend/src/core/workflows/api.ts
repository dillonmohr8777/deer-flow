import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import {
  JEVBOX_MAX_PROPOSAL_BYTES,
  parseJevboxPreparationStatus,
  parseJevboxProposal,
  validatePreparationUpload,
  type JevboxPreparationStatus,
  type JevboxProposalPreview,
} from "./jevbox-preparation";
import {
  type WorkflowDefinition,
  type WorkflowInput,
  type WorkflowRun,
  type WorkflowStatus,
} from "./types";

export class WorkflowApiError extends Error {
  constructor(
    public readonly code: string,
    public readonly status: number,
  ) {
    super(code);
    this.name = "WorkflowApiError";
  }
}
async function request(path: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(`${getBackendBaseURL()}/api/workflows${path}`, {
    ...init,
    cache: "no-store",
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: unknown;
    };
    throw new WorkflowApiError(
      typeof body.detail === "string" ? body.detail : "workflow_request_failed",
      response.status,
    );
  }
  if (
    response.redirected ||
    response.headers.get("content-type")?.split(";")[0] !== "application/json"
  )
    throw new WorkflowApiError("invalid_workflow_response", 502);
  return response;
}
async function json<T>(path: string, init?: RequestInit): Promise<T> {
  return (await request(path, init)).json() as Promise<T>;
}
function headers(scope: string): Record<string, string> {
  return { "X-Expected-Workflow-Scope": scope };
}

async function checkedJsonResponse<T>(
  response: Response,
  limit: number,
): Promise<T> {
  if (!response.ok) {
    throw new WorkflowApiError(
      response.status === 409
        ? "workspace_scope_changed"
        : "preparation_request_failed",
      response.status,
    );
  }
  if (
    response.redirected ||
    response.headers
      .get("content-type")
      ?.split(";")[0]
      ?.trim()
      .toLowerCase() !== "application/json"
  )
    throw new WorkflowApiError("invalid_workflow_response", 502);
  const declared = response.headers.get("content-length");
  if (
    declared !== null &&
    (!/^\d+$/.test(declared) || Number(declared) > limit)
  )
    throw new WorkflowApiError("invalid_workflow_response", 502);
  if (!response.body)
    throw new WorkflowApiError("invalid_workflow_response", 502);
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      size += next.value.byteLength;
      if (size > limit)
        throw new WorkflowApiError("invalid_workflow_response", 502);
      chunks.push(new Uint8Array(next.value));
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  try {
    return JSON.parse(
      new TextDecoder("utf-8", { fatal: true }).decode(bytes),
    ) as T;
  } catch {
    throw new WorkflowApiError("invalid_workflow_response", 502);
  }
}

async function jevboxRequest(
  path: string,
  init: RequestInit,
  limit: number,
): Promise<unknown> {
  const response = await fetch(`${getBackendBaseURL()}/api/workflows${path}`, {
    ...init,
    cache: "no-store",
  });
  return checkedJsonResponse(response, limit);
}

export interface WorkflowWorkspaceProjection {
  activeWorkspaceId: string | null;
}

function isWorkspaceProjection(value: unknown): value is {
  active_workspace_id: string | null;
  workspaces: { id: string; name: string; role: string }[];
} {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value) ||
    Object.keys(value).sort().join(",") !== "active_workspace_id,workspaces"
  )
    return false;
  const projection = value as Record<string, unknown>;
  return (
    (projection.active_workspace_id === null ||
      (typeof projection.active_workspace_id === "string" &&
        /^[A-Za-z0-9_-]{1,128}$/.test(projection.active_workspace_id))) &&
    Array.isArray(projection.workspaces) &&
    projection.workspaces.length <= 256 &&
    projection.workspaces.every(
      (workspace) =>
        typeof workspace === "object" &&
        workspace !== null &&
        !Array.isArray(workspace) &&
        Object.keys(workspace).sort().join(",") === "id,name,role" &&
        typeof (workspace as Record<string, unknown>).id === "string" &&
        /^[A-Za-z0-9_-]{1,128}$/.test((workspace as { id: string }).id) &&
        typeof (workspace as Record<string, unknown>).name === "string" &&
        Array.from((workspace as { name: string }).name).length <= 256 &&
        typeof (workspace as Record<string, unknown>).role === "string" &&
        (workspace as { role: string }).role.length <= 32,
    )
  );
}

export async function getWorkflowWorkspaceProjection(
  signal?: AbortSignal,
): Promise<WorkflowWorkspaceProjection> {
  const response = await fetch(`${getBackendBaseURL()}/api/workspaces`, {
    signal,
    cache: "no-store",
  });
  const value = await checkedJsonResponse<unknown>(response, 16_000);
  if (!isWorkspaceProjection(value))
    throw new WorkflowApiError("invalid_workflow_response", 502);
  return { activeWorkspaceId: value.active_workspace_id };
}

export async function getJevboxPreparationStatus(
  actor: string,
  signal?: AbortSignal,
): Promise<JevboxPreparationStatus> {
  const value = await jevboxRequest(
    "/jevbox/status",
    { signal, headers: { "X-Expected-User-Id": actor } },
    4096,
  );
  return parseJevboxPreparationStatus(value);
}

export async function prepareJevboxEvidence(
  file: File,
  scope: string,
  expected: { ownerId: string; workspaceId: string | null },
  signal?: AbortSignal,
): Promise<JevboxProposalPreview> {
  validatePreparationUpload(file);
  const fileBytes = await file.arrayBuffer();
  if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
  const packetHash = Array.from(
    new Uint8Array(await crypto.subtle.digest("SHA-256", fileBytes)),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("");
  const value = await jevboxRequest(
    "/jevbox/prepare",
    {
      method: "POST",
      signal,
      headers: { ...headers(scope), "Content-Type": "application/json" },
      body: file,
    },
    JEVBOX_MAX_PROPOSAL_BYTES,
  );
  if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
  return parseJevboxProposal(value, { ...expected, packetSha256: packetHash });
}
export function getWorkflowStatus(
  actor: string,
  signal?: AbortSignal,
): Promise<WorkflowStatus> {
  return json("/status", { signal, headers: { "X-Expected-User-Id": actor } });
}
export function getWorkflowCatalog(
  scope: string,
  signal?: AbortSignal,
): Promise<{ workflows: WorkflowDefinition[]; total: number }> {
  return json("/catalog", { signal, headers: headers(scope) });
}
export function listWorkflowRuns(
  scope: string,
  signal?: AbortSignal,
): Promise<{ runs: WorkflowRun[] }> {
  return json("/runs", { signal, headers: headers(scope) });
}
export function getWorkflowRun(
  id: string,
  scope: string,
  signal?: AbortSignal,
): Promise<WorkflowRun> {
  return json(`/runs/${encodeURIComponent(id)}`, {
    signal,
    headers: headers(scope),
  });
}
export function createWorkflowRun(
  input: WorkflowInput,
  key: string,
  scope: string,
  signal?: AbortSignal,
): Promise<WorkflowRun> {
  return json("/runs", {
    method: "POST",
    signal,
    headers: {
      ...headers(scope),
      "Content-Type": "application/json",
      "Idempotency-Key": key,
    },
    body: JSON.stringify(input),
  });
}
export function updateWorkflowRun(
  id: string,
  action: "cancel" | "resume",
  scope: string,
  signal?: AbortSignal,
): Promise<WorkflowRun> {
  return json(`/runs/${encodeURIComponent(id)}/${action}`, {
    method: "POST",
    signal,
    headers: headers(scope),
  });
}
export async function downloadWorkflowArtifact(
  id: string,
  scope: string,
  receipt: NonNullable<WorkflowRun["artifact"]>,
  signal?: AbortSignal,
): Promise<Blob> {
  const limit = 20 * 1024 * 1024;
  if (
    !Number.isSafeInteger(receipt.bytes) ||
    receipt.bytes < 0 ||
    receipt.bytes > limit ||
    !/^[a-f0-9]{64}$/i.test(receipt.sha256)
  )
    throw new Error(
      "The artifact receipt is invalid or exceeds the download limit.",
    );
  const response = await request(`/runs/${encodeURIComponent(id)}/artifact`, {
    signal,
    headers: headers(scope),
  });
  const declared = response.headers.get("content-length");
  if (
    declared !== null &&
    (!/^\d+$/.test(declared) ||
      Number(declared) > limit ||
      Number(declared) !== receipt.bytes)
  )
    throw new Error("The artifact size does not match its saved receipt.");
  if (!response.body) throw new Error("The artifact body is missing.");
  const reader = response.body.getReader();
  const chunks: Uint8Array<ArrayBuffer>[] = [];
  let bytes = 0;
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      bytes += next.value.byteLength;
      if (bytes > limit || bytes > receipt.bytes)
        throw new Error(
          "The artifact exceeds its saved size or download limit.",
        );
      chunks.push(new Uint8Array(next.value));
    }
  } finally {
    await reader.cancel();
    reader.releaseLock();
  }
  if (bytes !== receipt.bytes)
    throw new Error("The artifact size does not match its saved receipt.");
  const body = new Uint8Array(bytes);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.length;
  }
  const digest = await crypto.subtle.digest("SHA-256", body);
  const hash = Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
  if (hash !== receipt.sha256.toLowerCase())
    throw new Error("The artifact hash does not match its saved receipt.");
  if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
  return new Blob([body], { type: "application/json" });
}
export function isWorkflowScopeError(error: unknown): boolean {
  return error instanceof Error && error.message === "workspace_scope_changed";
}
export function isAdmissionUnconfirmed(error: unknown): boolean {
  if (
    error instanceof WorkflowApiError &&
    [400, 401, 403, 404, 422, 429].includes(error.status)
  )
    return false;
  return (
    !(error instanceof WorkflowApiError) ||
    ![
      "input_invalid",
      "idempotency_conflict",
      "queue_full",
      "daily_model_budget_exhausted",
      "framework_unavailable",
      "not_enabled",
      "workspace_scope_changed",
    ].includes(error.code)
  );
}
