import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export interface OpenAIAgentStatus {
  owner_scope: string;
  configured: boolean;
  sdk_version: string | null;
  available: boolean;
  model: string;
  max_concurrent_subagents: number;
  browser_available: boolean;
  reason: string | null;
}

export interface AgentSessionSummary {
  id: string;
  title: string;
  status: string;
  created_at: string;
  updated_at: string;
  last_error: string | null;
}

export interface AgentSession extends AgentSessionSummary {
  operation_pending: boolean;
  history_truncated: boolean;
  turn: { id: string; status: string; output_verified: boolean } | null;
  items: {
    id: string;
    type: string;
    turn_id: string | null;
    subagent_id: string | null;
    phase?: string | null;
    agent_id?: string | null;
    sender_agent_id?: string | null;
    recipient_agent_id?: string | null;
    role: string | null;
    text: string | null;
    status: string | null;
  }[];
  artifacts: {
    id: string;
    path: string;
    turn_id: string | null;
    content_url: string;
  }[];
  required_actions: unknown[];
  usage: { input_tokens: number | null; output_tokens: number | null } | null;
}

function url(path: string): string {
  return `${getBackendBaseURL()}/api/openai-agents${path}`;
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url(path), { ...init, cache: "no-store" });
  if (!response.ok)
    await throwGatewayApiError(response, "OpenAI agent request failed");
  return response.json() as Promise<T>;
}

export function getOpenAIAgentStatus(
  expectedUserId: string,
  signal?: AbortSignal,
): Promise<OpenAIAgentStatus> {
  return json("/status", {
    signal,
    headers: { "X-Expected-User-Id": expectedUserId },
  });
}

export function listAgentSessions(
  scope: string,
  signal?: AbortSignal,
): Promise<{ data: AgentSessionSummary[] }> {
  return json("/sessions", {
    signal,
    headers: { "X-Expected-Agent-Scope": scope },
  });
}

export function getAgentSession(
  id: string,
  scope: string,
  signal?: AbortSignal,
): Promise<AgentSession> {
  return json(`/sessions/${encodeURIComponent(id)}`, {
    signal,
    headers: { "X-Expected-Agent-Scope": scope },
  });
}

export function submitAgentInput(
  input: string,
  idempotencyKey: string,
  scope: string,
  sessionId?: string,
): Promise<AgentSession> {
  return json(
    sessionId
      ? `/sessions/${encodeURIComponent(sessionId)}/messages`
      : "/sessions",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
        "X-Expected-Agent-Scope": scope,
      },
      body: JSON.stringify({ input }),
    },
  );
}

export function cancelAgentTurn(
  sessionId: string,
  scope: string,
): Promise<AgentSession> {
  return json(`/sessions/${encodeURIComponent(sessionId)}/cancel`, {
    method: "POST",
    headers: { "X-Expected-Agent-Scope": scope },
  });
}

export function isAgentBusy(status: string): boolean {
  return [
    "creating",
    "in_progress",
    "running",
    "queued",
    "cancelling",
    "unknown",
    "requires_action",
  ].includes(status);
}

export async function downloadAgentArtifact(
  sessionId: string,
  artifactId: string,
  scope: string,
  signal?: AbortSignal,
): Promise<Blob> {
  const response = await fetch(
    url(
      `/sessions/${encodeURIComponent(sessionId)}/artifacts/${encodeURIComponent(artifactId)}/content`,
    ),
    {
      cache: "no-store",
      signal,
      headers: { "X-Expected-Agent-Scope": scope },
    },
  );
  if (!response.ok)
    await throwGatewayApiError(response, "Agent artifact download failed");
  if (
    response.headers.get("content-type")?.split(";")[0] !==
    "application/octet-stream"
  )
    throw new Error("The server did not return an agent file.");
  const maxBytes = 20 * 1024 * 1024;
  if (
    Number(response.headers.get("content-length")) > maxBytes ||
    !response.body
  )
    throw new Error("Agent file is unavailable or exceeds the download limit.");
  const reader = response.body.getReader();
  const chunks: Uint8Array<ArrayBuffer>[] = [];
  let bytes = 0;
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      bytes += chunk.value.byteLength;
      if (bytes > maxBytes)
        throw new Error("Agent file exceeds the download limit.");
      chunks.push(new Uint8Array(chunk.value));
    }
  } finally {
    await reader.cancel();
    reader.releaseLock();
  }
  return new Blob(chunks, { type: "application/octet-stream" });
}

export function handOffAgentDownload(blob: Blob, path: string): void {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = (path.split("/").pop() ?? "momobot-artifact")
    .replace(/[^\w.-]/g, "-")
    .slice(0, 120);
  try {
    document.body.append(anchor);
    anchor.click();
  } finally {
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 30_000);
  }
}
