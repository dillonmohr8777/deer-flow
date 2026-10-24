import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

/*
 * Per-person Composio connections (``backend/app/gateway/routers/composio_connect.py``).
 * The browser only ever holds an opaque handle: the provider's auth link stays
 * server-side behind ``GET /connect/{handle}/open``, which 302s once.
 */

export type ToolkitStatus = {
  toolkit: string;
  connected: boolean;
  connectable: boolean;
  reason: string | null;
};

export type ConnectAttempt = {
  handle: string;
  toolkit: string;
  expires_at: string;
};

export type ConnectRetry = {
  state: "not_requested" | "submitted" | "held";
  run_id?: string;
  source_run_id?: string;
  tool_call_id?: string;
  reason?: string;
};

export type ConnectResult = {
  handle: string;
  toolkit: string;
  status: "connected";
  retry: ConnectRetry;
};

/** A tool result asking for an account: ``{status: "no_connected_account", connect: {handle, toolkit}}``. */
export type ConnectHint = { handle: string; toolkit: string };

export const COMPOSIO_STATUS_QUERY_KEY = ["integrations", "composio"] as const;

const CALLBACK_PATH = "/api/integrations/callback";
const HANDLE = /^[A-Za-z0-9_-]{8,128}$/;

const base = () => `${getBackendBaseURL()}/api/integrations`;

async function detail(response: Response) {
  const body = (await response.json().catch(() => null)) as {
    detail?: unknown;
  } | null;
  return typeof body?.detail === "string" ? body.detail : response.statusText;
}

/** ``GET /status``. ``null`` when this server has no personal connections at all. */
export async function loadToolkitStatus(
  signal?: AbortSignal,
): Promise<ToolkitStatus[] | null> {
  const response = await fetchWithAuth(`${base()}/status`, {
    cache: "no-store",
    signal,
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(await detail(response));
  return ((await response.json()) as { toolkits: ToolkitStatus[] }).toolkits;
}

/** ``POST /connect`` -- mint an opaque attempt for one toolkit. */
export async function createConnectAttempt(
  toolkit: string,
): Promise<ConnectAttempt> {
  const response = await fetchWithAuth(`${base()}/connect`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ toolkit }),
  });
  if (!response.ok) throw new Error(await detail(response));
  return (await response.json()) as ConnectAttempt;
}

export function connectOpenURL(handle: string) {
  return `${base()}/connect/${encodeURIComponent(handle)}/open`;
}

/** Pull a connect request out of a tool result's text, if it carries one. */
export function parseConnectHint(text: string | undefined): ConnectHint | null {
  if (!text?.includes("no_connected_account")) return null;
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start < 0 || end <= start) return null;
  try {
    const value = JSON.parse(text.slice(start, end + 1)) as {
      status?: unknown;
      connect?: { handle?: unknown; toolkit?: unknown };
    };
    const { handle, toolkit } = value.connect ?? {};
    if (
      value.status !== "no_connected_account" ||
      typeof handle !== "string" ||
      typeof toolkit !== "string" ||
      !HANDLE.test(handle)
    ) {
      return null;
    }
    return { handle, toolkit };
  } catch {
    return null;
  }
}

/**
 * Open the provider in this attempt's own popup and resolve with the callback's
 * JSON. ``popup`` must be opened synchronously inside the click handler (before
 * any await) or browsers block it. The callback and the server's own ``/open``
 * errors land on our origin, so both are readable here. A callback for any
 * other handle or toolkit is rejected, never counted as this attempt's success.
 */
export function finishInPopup(
  popup: Window,
  attempt: ConnectHint,
  timeoutMs = 15 * 60 * 1000,
): Promise<ConnectResult> {
  const openPath = `/api/integrations/connect/${encodeURIComponent(attempt.handle)}/open`;
  popup.location.href = connectOpenURL(attempt.handle);
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const timer = window.setInterval(() => {
      const finish = (error: string | null, body?: ConnectResult) => {
        window.clearInterval(timer);
        if (!popup.closed) popup.close();
        if (error) reject(new Error(error));
        else resolve(body!);
      };
      if (popup.closed) return finish("connect_window_closed");
      if (Date.now() - started > timeoutMs)
        return finish("connect_attempt_expired");
      let path: string;
      let text: string;
      try {
        // Throws while the popup is on the provider's origin.
        path = popup.location.pathname;
        if (!path.endsWith(CALLBACK_PATH) && !path.endsWith(openPath)) return;
        if (popup.document.readyState !== "complete") return;
        text = popup.document.body?.innerText ?? "";
      } catch {
        return;
      }
      let body: (ConnectResult & { detail?: unknown }) | null = null;
      try {
        body = JSON.parse(text) as ConnectResult & { detail?: unknown };
      } catch {
        // An /open that is still redirecting has no JSON body yet.
        if (path.endsWith(openPath)) return;
      }
      if (body && typeof body.detail === "string") return finish(body.detail);
      if (path.endsWith(openPath)) return;
      if (
        body?.status !== "connected" ||
        body.handle !== attempt.handle ||
        body.toolkit !== attempt.toolkit
      ) {
        return finish(body ? "connect_result_mismatch" : "connect_failed");
      }
      finish(null, body);
    }, 500);
  });
}

/** True once the source run's ``composio.connected`` receipt is stored (it may land after ``run.end``). */
export async function hasConnectedReceipt(
  threadId: string,
  sourceRunId: string,
  handle: string,
): Promise<boolean> {
  const params = new URLSearchParams({
    event_types: "composio.connected",
    limit: "50",
  });
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(sourceRunId)}/events?${params}`,
    { cache: "no-store" },
  );
  if (!response.ok) return false;
  const events = (await response.json()) as {
    content?: { handle?: unknown };
  }[];
  return events.some((event) => event.content?.handle === handle);
}

const TOOLKIT_LABEL: Record<string, string> = {
  gmail: "Gmail",
  googlecalendar: "Google Calendar",
  googledrive: "Google Drive",
  googlesheets: "Google Sheets",
  googledocs: "Google Docs",
  slack: "Slack",
  hubspot: "HubSpot",
  googleads: "Google Ads",
  google_analytics: "Google Analytics",
  google_search_console: "Search Console",
  metaads: "Meta Ads",
  fireflies: "Fireflies",
  canva: "Canva",
  composio_search: "Web search",
};

export function toolkitLabel(toolkit: string) {
  return TOOLKIT_LABEL[toolkit] ?? toolkit;
}

/** Same id in both vocabularies: "google_calendar" matches "googlecalendar". */
export function sameToolkit(a: string, b: string) {
  const norm = (value: string) => value.toLowerCase().replace(/[^a-z0-9]/g, "");
  return norm(a) === norm(b);
}

const REASON: Record<string, string> = {
  no_account_required: "Ready. No account needed.",
  owner_setup_required: "Your workspace owner still has to switch this one on.",
  owner_setup_required_api_key:
    "Your workspace owner adds the key for this one. Nothing for you to do.",
  owner_setup_required_managed_oauth_unavailable:
    "Needs a one-time setup by your workspace owner first.",
  toolkit_not_allowed: "Not included for your account.",
  connect_attempt_held:
    "A connection is still being checked. Try again in a few minutes.",
  connection_verification_unavailable:
    "We couldn't check this connection right now. Try again shortly.",
  connection_selection_required:
    "More than one account is linked. Ask your workspace owner to pick one.",
  connect_disabled: "Personal connections aren't switched on yet.",
  legacy_connection_managed_separately: "Your admin manages this connection.",
  connect_window_closed: "The sign-in window closed before finishing.",
  connect_attempt_expired: "That sign-in link expired. Start again.",
  connect_attempt_not_found: "That sign-in link expired. Start again.",
  connect_open_consumed:
    "That sign-in link was already used. Press Connect to start a fresh one.",
  connect_result_mismatch:
    "That sign-in finished for a different connection. Press Connect to try again.",
  connect_attempt_in_progress:
    "A sign-in for this tool is already open. Finish it there first.",
  connect_nonce_denied: "Finish connecting in the same browser you started in.",
  composio_actor_denied: "This connection belongs to someone else.",
  connect_backend_unavailable: "Connections are briefly unavailable.",
  retry_admission_unavailable:
    "MomoBot couldn't pick the step back up. Ask it to try again.",
};

export function reasonText(reason: string | null | undefined) {
  if (!reason) return "";
  return REASON[reason] ?? "Not available yet.";
}

export function retryText(retry: ConnectRetry) {
  if (retry.state === "submitted")
    return "Connected. MomoBot is finishing the step it was waiting on.";
  if (retry.state === "held")
    return `Connected. The waiting step is on hold: ${reasonText(retry.reason ?? "retry_admission_unavailable")}`;
  return "Connected.";
}
