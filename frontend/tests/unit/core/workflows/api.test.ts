import { beforeEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));

import { fetch } from "@/core/api/fetcher";
import {
  createWorkflowRun,
  downloadWorkflowArtifact,
  getWorkflowCatalog,
  getWorkflowRun,
  getWorkflowStatus,
  isAdmissionUnconfirmed,
  listWorkflowRuns,
  updateWorkflowRun,
  WorkflowApiError,
} from "@/core/workflows/api";

const mockedFetch = rs.mocked(fetch);
function response(body = "{}") {
  return new Response(body, {
    headers: { "Content-Type": "application/json" },
  });
}
async function hash(text: string) {
  return Array.from(
    new Uint8Array(
      await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)),
    ),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("");
}
beforeEach(() => {
  mockedFetch.mockReset();
});

describe("Workflow Gateway requests", () => {
  it("pins actor status and every catalog/run/action request to the server-selected scope", async () => {
    mockedFetch.mockImplementation(async () => response());
    const signal = new AbortController().signal;
    await getWorkflowStatus("me", signal);
    await getWorkflowCatalog("scope", signal);
    await listWorkflowRuns("scope", signal);
    await getWorkflowRun("private/run", "scope", signal);
    await updateWorkflowRun("private/run", "resume", "scope", signal);
    expect(mockedFetch.mock.calls.map(([url]) => url)).toEqual([
      "/api/workflows/status",
      "/api/workflows/catalog",
      "/api/workflows/runs",
      "/api/workflows/runs/private%2Frun",
      "/api/workflows/runs/private%2Frun/resume",
    ]);
    expect(mockedFetch.mock.calls[0]?.[1]).toEqual({
      signal,
      cache: "no-store",
      headers: { "X-Expected-User-Id": "me" },
    });
    for (const call of mockedFetch.mock.calls.slice(1))
      expect(call[1]).toEqual(
        expect.objectContaining({
          signal,
          cache: "no-store",
          headers: { "X-Expected-Workflow-Scope": "scope" },
        }),
      );
  });
  it("preserves the caller's exact workflow payload, retry receipt, scope and abort signal", async () => {
    mockedFetch.mockResolvedValue(response());
    const input = {
        workflow_id: "launch",
        inputs: { brief: "Actual task" },
        framework: "langgraph" as const,
      },
      signal = new AbortController().signal;
    await createWorkflowRun(input, "stable-receipt", "scope", signal);
    expect(mockedFetch).toHaveBeenCalledWith("/api/workflows/runs", {
      signal,
      cache: "no-store",
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Expected-Workflow-Scope": "scope",
        "Idempotency-Key": "stable-receipt",
      },
      body: JSON.stringify(input),
    });
  });
  it("keeps scope and queue denials distinct from an unconfirmed provider outcome", async () => {
    mockedFetch.mockResolvedValue(
      new Response('{"detail":"workspace_scope_changed"}', { status: 409 }),
    );
    await expect(getWorkflowCatalog("old")).rejects.toThrow(
      "workspace_scope_changed",
    );
    expect(
      isAdmissionUnconfirmed(new WorkflowApiError("queue_full", 429)),
    ).toBe(false);
    expect(
      isAdmissionUnconfirmed(
        new WorkflowApiError("uncertain_provider_attempt", 409),
      ),
    ).toBe(true);
    expect(isAdmissionUnconfirmed(new Error("Connection lost"))).toBe(true);
    // FastAPI schema errors can carry a detail array, not a sanitized code.
    expect(isAdmissionUnconfirmed(new WorkflowApiError("HTTP422", 422))).toBe(
      false,
    );
  });
  it("rejects successful login HTML before displaying data or downloading", async () => {
    mockedFetch.mockResolvedValue(
      new Response("login", { headers: { "Content-Type": "text/html" } }),
    );
    await expect(getWorkflowRun("run", "scope")).rejects.toThrow(
      "invalid_workflow_response",
    );
    await expect(
      downloadWorkflowArtifact("run", "scope", {
        bytes: 2,
        sha256: await hash("{}"),
      }),
    ).rejects.toThrow("invalid_workflow_response");
  });
  it("downloads only the owned JSON artifact after exact byte and SHA-256 verification", async () => {
    mockedFetch.mockResolvedValue(response('{"accepted":true}'));
    const text = '{"accepted":true}',
      signal = new AbortController().signal;
    const blob = await downloadWorkflowArtifact(
      "private/run",
      "scope",
      { bytes: text.length, sha256: await hash(text) },
      signal,
    );
    expect(await blob.text()).toBe(text);
    expect(mockedFetch).toHaveBeenCalledWith(
      "/api/workflows/runs/private%2Frun/artifact",
      {
        signal,
        cache: "no-store",
        headers: { "X-Expected-Workflow-Scope": "scope" },
      },
    );
  });
  it("rejects truncated, excess and altered bytes against the durable receipt", async () => {
    const receipt = { bytes: 2, sha256: await hash("{}") };
    mockedFetch.mockResolvedValueOnce(response("{"));
    await expect(
      downloadWorkflowArtifact("run", "scope", receipt),
    ).rejects.toThrow("size does not match");
    mockedFetch.mockResolvedValueOnce(response("{}extra"));
    await expect(
      downloadWorkflowArtifact("run", "scope", receipt),
    ).rejects.toThrow("exceeds");
    mockedFetch.mockResolvedValueOnce(response("[]"));
    await expect(
      downloadWorkflowArtifact("run", "scope", receipt),
    ).rejects.toThrow("hash does not match");
  });
  it("rejects oversize metadata without opening any artifact response", async () => {
    await expect(
      downloadWorkflowArtifact("run", "scope", {
        bytes: 20 * 1024 * 1024 + 1,
        sha256: "a".repeat(64),
      }),
    ).rejects.toThrow("exceeds");
    expect(mockedFetch).not.toHaveBeenCalled();
  });
  it("cancels a bounded artifact reader before consuming its later chunks", async () => {
    let cancelled = false,
      reads = 0;
    const body = new ReadableStream<Uint8Array>(
      {
        pull(controller) {
          reads += 1;
          controller.enqueue(new TextEncoder().encode("too large"));
        },
        cancel() {
          cancelled = true;
        },
      },
      { highWaterMark: 0 },
    );
    mockedFetch.mockResolvedValue(
      new Response(body, { headers: { "Content-Type": "application/json" } }),
    );
    await expect(
      downloadWorkflowArtifact("run", "scope", {
        bytes: 2,
        sha256: await hash("{}"),
      }),
    ).rejects.toThrow("exceeds");
    expect(cancelled).toBe(true);
    expect(reads).toBe(1);
  });
});
