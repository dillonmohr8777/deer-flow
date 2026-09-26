import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { TeamChannel, TeamMember, TeamMessage } from "./types";

export const TEAM_CHANNELS_QUERY_KEY = ["team", "channels"] as const;
export const TEAM_MEMBERS_QUERY_KEY = ["team", "members"] as const;

export function teamMessagesQueryKey(channelId: string) {
  return ["team", "messages", channelId] as const;
}

async function readTeamAPIError(
  response: Response,
  fallback: string,
): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail) {
      return body.detail;
    }
  } catch {
    // Fall through to the caller-provided message.
  }
  return fallback;
}

async function getJSON<T>(path: string, fallback: string): Promise<T> {
  const response = await fetchWithAuth(`${getBackendBaseURL()}${path}`, {
    method: "GET",
  });
  if (!response.ok) {
    throw new Error(await readTeamAPIError(response, fallback));
  }
  return (await response.json()) as T;
}

async function postJSON<T>(
  path: string,
  body: unknown,
  fallback: string,
): Promise<T> {
  const response = await fetchWithAuth(`${getBackendBaseURL()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(await readTeamAPIError(response, fallback));
  }
  return (await response.json()) as T;
}

/** ``GET /api/team/channels`` -- the workspace's channels (defaults seeded). */
export async function listTeamChannels(): Promise<TeamChannel[]> {
  const body = await getJSON<{ channels: TeamChannel[] }>(
    "/api/team/channels",
    "Failed to load channels.",
  );
  return body.channels;
}

/** ``POST /api/team/channels`` -- owners and admins only. */
export async function createTeamChannel(input: {
  name: string;
  topic?: string;
}): Promise<TeamChannel> {
  return postJSON<TeamChannel>(
    "/api/team/channels",
    input,
    "Failed to add the channel.",
  );
}

/** ``GET /api/team/channels/{id}/messages`` -- oldest first. */
export async function listTeamMessages(
  channelId: string,
): Promise<TeamMessage[]> {
  const body = await getJSON<{ messages: TeamMessage[] }>(
    `/api/team/channels/${encodeURIComponent(channelId)}/messages`,
    "Failed to load messages.",
  );
  return body.messages;
}

/** ``POST /api/team/channels/{id}/messages`` -- the author is always you. */
export async function postTeamMessage(
  channelId: string,
  body: string,
): Promise<TeamMessage> {
  return postJSON<TeamMessage>(
    `/api/team/channels/${encodeURIComponent(channelId)}/messages`,
    { body },
    "Failed to send the message.",
  );
}

/** ``GET /api/team/members`` -- active staff, to name message authors. */
export async function listTeamMembers(): Promise<TeamMember[]> {
  const body = await getJSON<{ members: TeamMember[] }>(
    "/api/team/members",
    "Failed to load the team.",
  );
  return body.members;
}
