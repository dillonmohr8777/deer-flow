import type { StatusTone } from "@/components/workspace/page-body";

/**
 * Words for the codes the Browserbase service stores or raises
 * (`backend/app/gateway/browserbase_service.py`). The page never shows a
 * snake_case code: a known one gets its sentence, an unknown one the generic
 * sentence, and anything already written as a sentence passes through.
 */
const UNAVAILABLE =
  "Browser research is not available on this server right now.";
const NOT_SET_UP = "The capture browser is not set up on this server.";
const PROVIDER = "Browserbase did not answer as expected. Try again.";
const UNREACHABLE = "The page could not be reached.";
const RENDER = "The page opened, but its rendering could not be saved.";
const MINUTES =
  "Browser minutes could not be checked, so captures are paused until they can be.";
const CLEANUP =
  "The cloud session may still be open. Check your Browserbase minutes.";
const TIMEOUT = "The capture ran out of time.";

export const BROWSER_MESSAGES: Record<string, string> = {
  invalid_public_url: "Use a full public address that starts with https://.",
  private_network_blocked:
    "That address points to a private network, so it was not opened.",
  secret_bearing_url:
    "That address carries a key or password, so it was not opened.",
  page_too_large: "The page is too large to capture.",
  unsupported_content_encoding: "The page is not text the capture can read.",
  unsupported_public_content: "The page is not text the capture can read.",
  dns_resolution_failed: "The site's address could not be found.",
  public_page_fetch_failed: UNREACHABLE,
  public_page_unavailable: UNREACHABLE,
  invalid_redirect: "The page redirected somewhere the capture cannot follow.",
  too_many_redirects: "The page redirected too many times.",
  not_found: "This capture no longer exists.",
  idempotency_conflict:
    "That request was already sent with different pages. Start a new capture.",
  owner_busy: "A capture is already queued or running. Wait for it to finish.",
  duplicate_public_url: "The same page is listed twice.",
  invalid_page_count: "List at least one page, and no more than the limit.",
  invalid_title: "Shorten the capture title.",
  invalid_idempotency_key: "The request could not be confirmed. Try again.",
  not_enabled: "Browser research is turned off on this server.",
  provider_unconfigured: "Browserbase is not connected on this server.",
  provider_unavailable: UNAVAILABLE,
  service_unavailable: UNAVAILABLE,
  service_already_running: UNAVAILABLE,
  service_stopping: UNAVAILABLE,
  process_lock_unavailable: UNAVAILABLE,
  browser_minutes_exhausted: "This month's browser minutes are used up.",
  organization_usage_unverified: MINUTES,
  monthly_limit_unverified: MINUTES,
  unverified_quota: MINUTES,
  provider_request_failed: PROVIDER,
  invalid_provider_response: PROVIDER,
  invalid_provider_connection: PROVIDER,
  invalid_provider_endpoint: PROVIDER,
  provider_create_uncertain:
    "Browserbase may have started a session that could not be confirmed. Check your minutes before trying again.",
  browser_dependency_missing: NOT_SET_UP,
  browser_worker_not_installed: NOT_SET_UP,
  browser_worker_identity_mismatch: NOT_SET_UP,
  browser_worker_protocol_error: NOT_SET_UP,
  invalid_server_extension: NOT_SET_UP,
  stagehand_runner_required: NOT_SET_UP,
  stagehand_extension_required: NOT_SET_UP,
  stagehand_extension_unavailable: NOT_SET_UP,
  stagehand_extension_inspection_failed: NOT_SET_UP,
  stagehand_runtime_incompatible: NOT_SET_UP,
  stagehand_initialization_failed: NOT_SET_UP,
  browser_render_failed: RENDER,
  browser_snapshot_render_failed: RENDER,
  browser_snapshot_capture_failed: RENDER,
  invalid_screenshot: RENDER,
  invalid_browser_snapshot: RENDER,
  research_timeout: TIMEOUT,
  stagehand_operation_timeout: TIMEOUT,
  interrupted_by_restart: "The server restarted during the capture.",
  browser_cleanup_unconfirmed: CLEANUP,
  browser_cleanup_failed: CLEANUP,
  browser_operation_failed:
    "The cloud browser stopped partway through the capture.",
  browser_worker_failed:
    "The cloud browser stopped partway through the capture.",
  browser_model_input_invalid: "The page could not be read for the capture.",
  browser_model_call_limit:
    "The capture reached its reading limit before it finished.",
  stagehand_observation_failed: "The page could not be read for the capture.",
  stagehand_extraction_failed: "The page text could not be extracted.",
  browser_session_unavailable: "The cloud browser session could not start.",
  browser_transport_failed: "The connection to the cloud browser dropped.",
  workspace_scope_changed:
    "The workspace changed. Refresh to read its captures.",
};

export const BROWSER_GENERIC = "The capture could not be completed.";

/** A stored or raised code, or an Error carrying one, in words. */
export function browserWords(value: unknown): string {
  const text =
    value instanceof Error
      ? value.message
      : typeof value === "string"
        ? value
        : "";
  const code = text.trim();
  if (!code) return BROWSER_GENERIC;
  if (BROWSER_MESSAGES[code]) return BROWSER_MESSAGES[code];
  if (/^[a-z][a-z0-9_]*$/.test(code)) return BROWSER_GENERIC;
  return code;
}

/** A capture's state as the board says it: only running work is Working. */
export function captureState(status: string): {
  label: string;
  tone: StatusTone;
} {
  switch (status) {
    case "running":
      return { label: "Working", tone: "active" };
    case "queued":
      return { label: "Queued", tone: "idle" };
    case "completed":
      return { label: "Captured", tone: "ok" };
    case "failed":
      return { label: "Failed", tone: "danger" };
    case "cancelled":
      return { label: "Stopped", tone: "idle" };
    default:
      return { label: "Unknown", tone: "unknown" };
  }
}
