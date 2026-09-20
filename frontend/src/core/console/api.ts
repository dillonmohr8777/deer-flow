import { getAPIClient } from "@/core/api";
import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { ConsoleRunsResponse, ConsoleStats, ConsoleUsage } from "./types";

async function getJSON<T>(path: string): Promise<T> {
  const response = await fetchWithAuth(`${getBackendBaseURL()}${path}`, {
    method: "GET",
  });
  if (!response.ok)
    throw new Error(`Console request failed (${response.status})`);
  return (await response.json()) as T;
}

export const fetchConsoleStats = () =>
  getJSON<ConsoleStats>("/api/console/stats");

export function fetchConsoleRuns({
  status,
  offset = 0,
}: { status?: string; offset?: number } = {}) {
  const params = new URLSearchParams({ limit: "20", offset: String(offset) });
  if (status) params.set("status", status);
  return getJSON<ConsoleRunsResponse>(`/api/console/runs?${params.toString()}`);
}

export function fetchConsoleUsage() {
  // Date#getTimezoneOffset is UTC - local; the Gateway expects local - UTC.
  const tzOffset = -new Date().getTimezoneOffset();
  return getJSON<ConsoleUsage>(
    `/api/console/usage?days=14&tz_offset_minutes=${encodeURIComponent(String(tzOffset))}`,
  );
}

export async function cancelConsoleRun(threadId: string, runId: string) {
  await getAPIClient().runs.cancel(threadId, runId);
}
