import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export type ServiceTier = "software" | "am_assisted" | "standard";

/** Plain-language names and what each tier means day to day. No prices here by design. */
export const TIER_COPY: Record<ServiceTier, { name: string; summary: string }> =
  {
    software: {
      name: "Software subscription",
      summary:
        "The client checks and approves Momo's work in their own portal. No account manager. They can book a call if they need one.",
    },
    am_assisted: {
      name: "Account manager assisted",
      summary:
        "Momo prepares the work. The account manager reviews it and sends it to the client.",
    },
    standard: {
      name: "Standard",
      summary:
        "The account manager runs the relationship. Momo is optional and stays with the team; the client does not chat with Momo.",
    },
  };

export type PlanItem = {
  title: string;
  kind: string;
  kind_label: string;
  cadence: string;
  cadence_label: string;
  cron: string | null;
};

export type PlanPreview = {
  items: PlanItem[];
  recurring: number;
  one_time: number;
  cadences: { id: string; label: string }[];
  kinds: { id: string; label: string }[];
};

export type ServiceSettings = {
  workspace_id: string;
  workspace_name: string;
  service_tier: ServiceTier | null;
  booking_url: string | null;
  sold_by_user_id: string | null;
  check_in_task_id: string | null;
  onboarding: {
    applied_at: string;
    items: (PlanItem & { task_id?: string })[];
    tasks_paused: boolean;
  } | null;
  version: number;
  can_edit: boolean;
  tiers: ServiceTier[];
};

async function call<T>(path: string, method: string, body?: unknown) {
  const response = await fetch(`${getBackendBaseURL()}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  if (!response.ok) {
    const error = (await response.json().catch(() => ({}))) as {
      detail?: unknown;
    };
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : "Something went wrong. Refresh and try again.",
    );
  }
  return (await response.json()) as T;
}

const id = (workspaceId: string) => encodeURIComponent(workspaceId);

export const getServiceSettings = (workspaceId: string) =>
  call<ServiceSettings>(`/api/workspaces/${id(workspaceId)}/service`, "GET");

export const updateServiceSettings = (
  workspaceId: string,
  body: {
    service_tier: ServiceTier | null;
    booking_url: string | null;
    sold_by_user_id: string | null;
    expected_version: number;
  },
) =>
  call<ServiceSettings>(
    `/api/workspaces/${id(workspaceId)}/service`,
    "PUT",
    body,
  );

export const previewOnboarding = (workspaceId: string, contractText: string) =>
  call<PlanPreview>(`/api/onboarding/${id(workspaceId)}/preview`, "POST", {
    contract_text: contractText,
  });

export const applyOnboarding = (
  workspaceId: string,
  body: {
    contract_text: string;
    expected_version: number;
    workspace_name: string | null;
    items: { title: string; cadence: string; kind: string }[];
    timezone: string;
  },
) =>
  call<ServiceSettings>(
    `/api/onboarding/${id(workspaceId)}/apply`,
    "POST",
    body,
  );
