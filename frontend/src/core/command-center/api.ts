import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { BoardData, SpendReport } from "./types";

async function getJSON<T>(path: string): Promise<T> {
  const response = await fetchWithAuth(`${getBackendBaseURL()}${path}`, {
    method: "GET",
  });
  if (response.status === 403)
    throw new Error("Only a workspace administrator can see this.");
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return (await response.json()) as T;
}

export const fetchBoard = () => getJSON<BoardData>("/api/command-center/board");
export const fetchSpend = () => getJSON<SpendReport>("/api/cost-router/spend");
