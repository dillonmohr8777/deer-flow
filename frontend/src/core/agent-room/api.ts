import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";
import { isDeskEnabled, type FeaturesResponse } from "@/core/features/api";

import type { AgentRoomMessage, AgentRoomMessageType } from "./types";

export const AGENT_ROOM_MESSAGES_QUERY_KEY = [
  "agent-room",
  "messages",
] as const;

async function readError(
  response: Response,
  fallback: string,
): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail) return body.detail;
  } catch {
    // Use the local message when the response is not JSON.
  }
  return fallback;
}

// Thrown only for a response that actually denies access (403/404). A
// transient failure (network error, 5xx) must never be confused with this:
// callers use it to decide whether to revoke a previously granted session,
// where an ordinary hiccup should not.
export class AgentRoomAccessDeniedError extends Error {
  constructor() {
    super("Private room access was denied.");
    this.name = "AgentRoomAccessDeniedError";
  }
}

export async function fetchAgentRoomEnabled(
  ownerId: string,
  signal?: AbortSignal,
): Promise<boolean> {
  const response = await fetchWithAuth(`${getBackendBaseURL()}/api/features`, {
    signal,
    headers: { "X-Expected-User-Id": ownerId },
  });
  if (response.status === 403 || response.status === 404) {
    throw new AgentRoomAccessDeniedError();
  }
  if (!response.ok) throw new Error("Private room access is unavailable.");
  return isDeskEnabled((await response.json()) as FeaturesResponse);
}

export async function listAgentRoomMessages(
  ownerId: string,
  signal?: AbortSignal,
): Promise<AgentRoomMessage[]> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/agent-room/messages?limit=100`,
    { method: "GET", signal, headers: { "X-Expected-User-Id": ownerId } },
  );
  if (!response.ok) {
    throw new Error(
      await readError(response, "Failed to load the Agent Room."),
    );
  }
  const result = (await response.json()) as { messages: AgentRoomMessage[] };
  return result.messages;
}

export async function postAgentRoomMessage(
  input: {
    body: string;
    message_type: Extract<AgentRoomMessageType, "instruction" | "note">;
  },
  ownerId: string,
): Promise<AgentRoomMessage> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/agent-room/messages`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Expected-User-Id": ownerId,
      },
      body: JSON.stringify(input),
    },
  );
  if (!response.ok) {
    throw new Error(
      await readError(response, "Failed to post to the Agent Room."),
    );
  }
  return (await response.json()) as AgentRoomMessage;
}
