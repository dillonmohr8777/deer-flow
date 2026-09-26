import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  BoardMessage,
  BoardThread,
  BoardThreadKind,
  BoardThreadStatus,
} from "./types";

export const BOARD_THREADS_QUERY_KEY = ["board", "threads"] as const;

export function boardThreadQueryKey(threadId: string) {
  return ["board", "thread", threadId] as const;
}

export function boardMessagesQueryKey(threadId: string) {
  return ["board", "messages", threadId] as const;
}

async function readBoardAPIError(
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

/** ``GET /api/board/threads`` -- the thread roster, optionally filtered. */
export async function listBoardThreads(params?: {
  clientId?: string;
  status?: BoardThreadStatus;
}): Promise<BoardThread[]> {
  const search = new URLSearchParams();
  if (params?.clientId) search.set("client_id", params.clientId);
  if (params?.status) search.set("status", params.status);
  const qs = search.toString();
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/board/threads${qs ? `?${qs}` : ""}`,
    { method: "GET" },
  );
  if (!response.ok) {
    throw new Error(
      await readBoardAPIError(response, "Failed to load board threads."),
    );
  }
  const body = (await response.json()) as { threads: BoardThread[] };
  return body.threads;
}

/**
 * ``POST /api/board/threads`` -- start a new post, ticket, concern or DM.
 * Any org member assigned to ``clientId`` (a client contact included) may
 * call this; the backend 404s a client the caller can't reach.
 */
export async function createBoardThread(input: {
  clientId: string;
  kind: BoardThreadKind;
  subject: string;
}): Promise<BoardThread> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/board/threads`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_id: input.clientId,
        kind: input.kind,
        subject: input.subject,
      }),
    },
  );
  if (!response.ok) {
    throw new Error(
      await readBoardAPIError(response, "Failed to start the thread."),
    );
  }
  return (await response.json()) as BoardThread;
}

/** ``GET /api/board/threads/{id}`` -- one thread. */
export async function getBoardThread(threadId: string): Promise<BoardThread> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/board/threads/${threadId}`,
    { method: "GET" },
  );
  if (!response.ok) {
    throw new Error(
      await readBoardAPIError(response, "Failed to load the thread."),
    );
  }
  return (await response.json()) as BoardThread;
}

/** ``GET /api/board/threads/{id}/messages`` -- a thread's message history. */
export async function listBoardMessages(
  threadId: string,
): Promise<BoardMessage[]> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/board/threads/${threadId}/messages`,
    { method: "GET" },
  );
  if (!response.ok) {
    throw new Error(
      await readBoardAPIError(response, "Failed to load messages."),
    );
  }
  const body = (await response.json()) as { messages: BoardMessage[] };
  return body.messages;
}

/**
 * ``POST /api/board/threads/{id}/draft`` -- Momo drafts a reply; moves the
 * thread from ``new``/``triaged`` to ``drafted``.
 */
export async function draftBoardReply(
  threadId: string,
  body: string,
): Promise<BoardThread> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/board/threads/${threadId}/draft`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body }),
    },
  );
  if (!response.ok) {
    throw new Error(
      await readBoardAPIError(response, "Failed to save the draft."),
    );
  }
  return (await response.json()) as BoardThread;
}

/**
 * ``POST /api/board/threads/{id}/approve`` -- an org owner/admin approves a
 * drafted reply; moves the thread from ``drafted`` to ``approved``.
 */
export async function approveBoardReply(
  threadId: string,
): Promise<BoardThread> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/board/threads/${threadId}/approve`,
    { method: "POST" },
  );
  if (!response.ok) {
    throw new Error(
      await readBoardAPIError(response, "Failed to approve the draft."),
    );
  }
  return (await response.json()) as BoardThread;
}

/**
 * ``POST /api/board/threads/{id}/reply`` -- an org owner/admin sends the
 * reply; moves the thread from ``approved`` to ``replied``.
 */
export async function sendBoardReply(
  threadId: string,
  body: string,
): Promise<BoardThread> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/board/threads/${threadId}/reply`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body }),
    },
  );
  if (!response.ok) {
    throw new Error(
      await readBoardAPIError(response, "Failed to send the reply."),
    );
  }
  return (await response.json()) as BoardThread;
}
