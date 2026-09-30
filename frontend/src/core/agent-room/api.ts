import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

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

export async function listAgentRoomMessages(): Promise<AgentRoomMessage[]> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/agent-room/messages?limit=100`,
    { method: "GET" },
  );
  if (!response.ok) {
    throw new Error(
      await readError(response, "Failed to load the Agent Room."),
    );
  }
  const result = (await response.json()) as { messages: AgentRoomMessage[] };
  return result.messages;
}

export async function postAgentRoomMessage(input: {
  body: string;
  message_type: Extract<AgentRoomMessageType, "instruction" | "note">;
}): Promise<AgentRoomMessage> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/agent-room/messages`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
