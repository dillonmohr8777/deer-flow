import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { Client } from "./types";

export type ClientListResponse = {
  clients: Client[];
};

export const CLIENTS_QUERY_KEY = ["clients"] as const;

async function readClientAPIError(
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

/** ``GET /api/clients`` -- the client roster (Client Spaces view). */
export async function listClients(): Promise<Client[]> {
  const response = await fetchWithAuth(`${getBackendBaseURL()}/api/clients`, {
    method: "GET",
  });

  if (!response.ok) {
    throw new Error(
      await readClientAPIError(response, "Failed to load clients."),
    );
  }

  const body = (await response.json()) as ClientListResponse;
  return body.clients;
}
