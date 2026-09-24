import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export type AuditEvent = {
  id: string;
  occurred_at: string;
  actor_user_id: string | null;
  organization_id: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  outcome: string;
  ip: string | null;
  user_agent: string | null;
  details: Record<string, unknown> | null;
};

export type AuditEventFilters = {
  actionPrefix?: string;
  actor?: string;
  since?: string;
  until?: string;
  cursor?: string;
  limit?: number;
};

export type AuditEventPage = {
  events: AuditEvent[];
  next_cursor: string | null;
};

export async function loadAuditEvents(
  filters: AuditEventFilters = {},
  signal?: AbortSignal,
): Promise<AuditEventPage> {
  const params = new URLSearchParams();
  if (filters.actionPrefix) params.set("action_prefix", filters.actionPrefix);
  if (filters.actor) params.set("actor", filters.actor);
  if (filters.since) params.set("since", filters.since);
  if (filters.until) params.set("until", filters.until);
  if (filters.cursor) params.set("cursor", filters.cursor);
  params.set("limit", String(filters.limit ?? 50));

  const response = await fetch(
    `${getBackendBaseURL()}/api/admin/audit-events?${params.toString()}`,
    { signal },
  );
  if (!response.ok)
    await throwGatewayApiError(response, "Audit log request failed");
  return response.json() as Promise<AuditEventPage>;
}
