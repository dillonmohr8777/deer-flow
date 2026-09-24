import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { FleetAgentBinding, FleetTemplate } from "./types";

export const FLEET_TEMPLATES_QUERY_KEY = ["fleet", "templates"] as const;

export function clientAgentsQueryKey(clientId: string) {
  return ["clients", clientId, "agents"] as const;
}

async function readFleetAPIError(
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

/** ``GET /api/fleet/templates``; the fleet template catalog. */
export async function listFleetTemplates(): Promise<FleetTemplate[]> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/fleet/templates`,
    { method: "GET" },
  );

  if (!response.ok) {
    throw new Error(
      await readFleetAPIError(response, "Failed to load fleet templates."),
    );
  }

  const body = (await response.json()) as { templates: FleetTemplate[] };
  return body.templates;
}

/** ``GET /api/clients/{client_id}/agents``; this client's stamped agents. */
export async function listClientAgents(
  clientId: string,
): Promise<FleetAgentBinding[]> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/clients/${clientId}/agents`,
    { method: "GET" },
  );

  if (!response.ok) {
    throw new Error(
      await readFleetAPIError(response, "Failed to load this client's agents."),
    );
  }

  const body = (await response.json()) as { agents: FleetAgentBinding[] };
  return body.agents;
}

/**
 * ``POST /api/clients/{client_id}/agents``; stamp a template into an agent
 * for this client. Idempotent on the backend: stamping the same template
 * twice for one client returns the existing agent rather than a duplicate.
 */
export async function stampClientAgent(
  clientId: string,
  templateId: string,
): Promise<FleetAgentBinding> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/clients/${clientId}/agents`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ template_id: templateId }),
    },
  );

  if (!response.ok) {
    throw new Error(
      await readFleetAPIError(
        response,
        "Failed to add an agent from this template.",
      ),
    );
  }

  return response.json() as Promise<FleetAgentBinding>;
}
