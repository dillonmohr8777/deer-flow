import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  DailyDigest,
  NeedsMyYes,
  SeatActionResult,
  SeatRosterEntry,
} from "./types";

export const CEO_NEEDS_MY_YES_QUERY_KEY = ["ceo", "needs-my-yes"] as const;
export const CEO_SEATS_QUERY_KEY = ["ceo", "seats"] as const;
export const CEO_DIGEST_QUERY_KEY = ["ceo", "digest"] as const;

async function readCeoAPIError(
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
    throw new Error(await readCeoAPIError(response, fallback));
  }
  return (await response.json()) as T;
}

async function postJSON<T>(path: string, fallback: string): Promise<T> {
  const response = await fetchWithAuth(`${getBackendBaseURL()}${path}`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await readCeoAPIError(response, fallback));
  }
  return (await response.json()) as T;
}

/** ``GET /api/ceo/needs-my-yes`` -- drafted board threads plus claimed seats. */
export async function getNeedsMyYes(): Promise<NeedsMyYes> {
  return getJSON<NeedsMyYes>(
    "/api/ceo/needs-my-yes",
    "Failed to load what needs your yes.",
  );
}

/** ``GET /api/ceo/seats`` -- the agent-seat roster with trailing-week burn. */
export async function getSeatRoster(): Promise<SeatRosterEntry[]> {
  const body = await getJSON<{ seats: SeatRosterEntry[] }>(
    "/api/ceo/seats",
    "Failed to load the seat roster.",
  );
  return body.seats;
}

/** ``GET /api/ceo/digest`` -- the most recently generated daily digest, if any. */
export async function getDailyDigest(): Promise<DailyDigest | null> {
  const body = await getJSON<{ digest: DailyDigest | null }>(
    "/api/ceo/digest",
    "Failed to load the daily digest.",
  );
  return body.digest;
}

/** ``POST /api/ceo/seats/{id}/ratify`` -- one-tap confirm a claimed seat. */
export async function ratifySeat(seatId: string): Promise<SeatActionResult> {
  return postJSON<SeatActionResult>(
    `/api/ceo/seats/${encodeURIComponent(seatId)}/ratify`,
    "Failed to ratify the seat.",
  );
}

/** ``POST /api/ceo/seats/{id}/reopen`` -- one-tap veto a claimed or ratified seat. */
export async function reopenSeat(seatId: string): Promise<SeatActionResult> {
  return postJSON<SeatActionResult>(
    `/api/ceo/seats/${encodeURIComponent(seatId)}/reopen`,
    "Failed to reopen the seat.",
  );
}
