import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export interface BrowserbaseStatus {
  owner_scope: string;
  configured: boolean;
  available: boolean;
  reason: string | null;
  browser_minutes: number | null;
  monthly_minute_limit: number | null;
  remaining_minutes: number | null;
  mode: "public_read_only_snapshot";
  limits: {
    max_pages: number;
    session_timeout_seconds: number;
    max_sessions_per_owner: number;
  };
}

export interface BrowserResearchSummary {
  id: string;
  title: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  created_at: string;
  updated_at: string;
  last_error: string | null;
}

export interface BrowserResearch extends BrowserResearchSummary {
  urls: string[];
  pages: {
    index: number;
    url: string;
    final_url: string;
    title: string;
    text: string;
    content_type: string;
    screenshot_url: string | null;
    source_mode: "public_read_only_snapshot";
  }[];
  session_id: string | null;
  replay_url: string | null;
  session_closed: boolean | null;
  usage: {
    browser_minutes: number | null;
    elapsed_seconds: number;
    cost_usd: null;
  };
}

export interface BrowserResearchInput {
  urls: string[];
  title?: string;
}

function url(path: string): string {
  return `${getBackendBaseURL()}/api/browserbase${path}`;
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(url(path), { ...init, cache: "no-store" });
  if (!response.ok)
    await throwGatewayApiError(response, "Browser research request failed");
  return response;
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  return (await request(path, init)).json() as Promise<T>;
}

export function getBrowserbaseStatus(
  expectedUserId: string,
  signal?: AbortSignal,
): Promise<BrowserbaseStatus> {
  return json("/status", {
    signal,
    headers: { "X-Expected-User-Id": expectedUserId },
  });
}

export function listBrowserResearch(
  scope: string,
  signal?: AbortSignal,
): Promise<{ data: BrowserResearchSummary[] }> {
  return json("/research", {
    signal,
    headers: { "X-Expected-Browserbase-Scope": scope },
  });
}

export function getBrowserResearch(
  id: string,
  scope: string,
  signal?: AbortSignal,
): Promise<BrowserResearch> {
  return json(`/research/${encodeURIComponent(id)}`, {
    signal,
    headers: { "X-Expected-Browserbase-Scope": scope },
  });
}

export function createBrowserResearch(
  input: BrowserResearchInput,
  idempotencyKey: string,
  scope: string,
): Promise<BrowserResearch> {
  return json("/research", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
      "X-Expected-Browserbase-Scope": scope,
    },
    body: JSON.stringify(input),
  });
}

export function cancelBrowserResearch(
  id: string,
  scope: string,
): Promise<BrowserResearch> {
  return json(`/research/${encodeURIComponent(id)}/cancel`, {
    method: "POST",
    headers: { "X-Expected-Browserbase-Scope": scope },
  });
}

/** Construct an owned Gateway path; never fetch a provider-controlled image URL. */
export async function loadBrowserResearchScreenshot(
  id: string,
  index: number,
  scope: string,
  signal?: AbortSignal,
): Promise<Blob> {
  if (!Number.isSafeInteger(index) || index < 0 || index > 2)
    throw new Error("Invalid captured page index");
  const response = await request(
    `/research/${encodeURIComponent(id)}/pages/${index}/screenshot`,
    { signal, headers: { "X-Expected-Browserbase-Scope": scope } },
  );
  if (response.headers.get("content-type")?.split(";")[0] !== "image/png")
    throw new Error("The server did not return a captured screenshot.");
  const maxBytes = 20 * 1024 * 1024;
  const size = Number(response.headers.get("content-length"));
  if (Number.isFinite(size) && size > maxBytes)
    throw new Error("The screenshot exceeds the download limit.");
  if (!response.body) throw new Error("The screenshot body is missing.");
  const reader = response.body.getReader();
  const chunks: Uint8Array<ArrayBuffer>[] = [];
  let bytes = 0;
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      bytes += chunk.value.byteLength;
      if (bytes > maxBytes)
        throw new Error("The screenshot exceeds the download limit.");
      chunks.push(new Uint8Array(chunk.value));
    }
  } finally {
    await reader.cancel();
    reader.releaseLock();
  }
  if (!bytes) throw new Error("The screenshot body is empty.");
  return new Blob(chunks, { type: "image/png" });
}

export function isBrowserResearchBusy(status: string): boolean {
  return status === "queued" || status === "running";
}

export function handOffResearchDownload(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  try {
    document.body.append(anchor);
    anchor.click();
  } finally {
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 30_000);
  }
}
