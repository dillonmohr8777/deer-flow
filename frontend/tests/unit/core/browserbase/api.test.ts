import { beforeEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));

import { fetch } from "@/core/api/fetcher";
import {
  createBrowserResearch,
  getBrowserbaseStatus,
  getBrowserResearch,
  loadBrowserResearchScreenshot,
} from "@/core/browserbase/api";

const mockedFetch = rs.mocked(fetch);
beforeEach(() => {
  mockedFetch.mockReset();
});

describe("Browserbase Gateway requests", () => {
  it("pins actor identity and rejects stale cookie scopes before displaying a successful capture", async () => {
    mockedFetch.mockImplementation(
      async () =>
        new Response('{"detail":"workspace_scope_changed"}', { status: 409 }),
    );
    await expect(getBrowserbaseStatus("owner-one")).rejects.toThrow(
      "workspace_scope_changed",
    );
    expect(mockedFetch).toHaveBeenCalledWith("/api/browserbase/status", {
      signal: undefined,
      cache: "no-store",
      headers: { "X-Expected-User-Id": "owner-one" },
    });
    await expect(
      getBrowserResearch("private", "old-workspace"),
    ).rejects.toThrow("workspace_scope_changed");
    await expect(
      loadBrowserResearchScreenshot("private", 0, "old-workspace"),
    ).rejects.toThrow("workspace_scope_changed");
  });
  it("keeps a stable receipt on paid-session admission and uses the authenticated fetcher", async () => {
    mockedFetch.mockResolvedValue(
      new Response("{}", { headers: { "Content-Type": "application/json" } }),
    );
    await createBrowserResearch(
      { urls: ["https://openai.com/"] },
      "stable-receipt",
      "scope-one",
    );
    expect(mockedFetch).toHaveBeenCalledWith("/api/browserbase/research", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": "stable-receipt",
        "X-Expected-Browserbase-Scope": "scope-one",
      },
      body: JSON.stringify({ urls: ["https://openai.com/"] }),
      cache: "no-store",
    });
  });

  it("aborts stale-owner reads and preserves owner denial as an error", async () => {
    const controller = new AbortController();
    mockedFetch.mockResolvedValue(
      new Response('{"detail":"not_found"}', { status: 404 }),
    );
    await expect(
      getBrowserResearch("another/owner", "scope-one", controller.signal),
    ).rejects.toThrow("not_found");
    expect(mockedFetch).toHaveBeenCalledWith(
      "/api/browserbase/research/another%2Fowner",
      {
        signal: controller.signal,
        headers: { "X-Expected-Browserbase-Scope": "scope-one" },
        cache: "no-store",
      },
    );
  });

  it("retrieves only an owned PNG path and rejects HTML before displaying it", async () => {
    mockedFetch.mockResolvedValue(
      new Response("<html>login</html>", {
        headers: { "Content-Type": "text/html" },
      }),
    );
    await expect(
      loadBrowserResearchScreenshot("private/run", 0, "scope-one"),
    ).rejects.toThrow("did not return a captured screenshot");
    expect(mockedFetch).toHaveBeenCalledWith(
      "/api/browserbase/research/private%2Frun/pages/0/screenshot",
      {
        signal: undefined,
        headers: { "X-Expected-Browserbase-Scope": "scope-one" },
        cache: "no-store",
      },
    );
    mockedFetch.mockClear();
    await expect(
      loadBrowserResearchScreenshot("id", 3, "scope-one"),
    ).rejects.toThrow("Invalid captured page index");
    expect(mockedFetch).not.toHaveBeenCalled();
  });

  it("bounds screenshot downloads before and during body consumption", async () => {
    mockedFetch.mockResolvedValue(
      new Response("small", {
        headers: {
          "Content-Type": "image/png",
          "Content-Length": String(21 * 1024 * 1024),
        },
      }),
    );
    await expect(
      loadBrowserResearchScreenshot("id", 0, "scope-one"),
    ).rejects.toThrow("download limit");
    const cancel = rs.fn();
    const oversized = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array(20 * 1024 * 1024 + 1));
      },
      cancel,
    });
    mockedFetch.mockResolvedValue(
      new Response(oversized, { headers: { "Content-Type": "image/png" } }),
    );
    await expect(
      loadBrowserResearchScreenshot("id", 0, "scope-one"),
    ).rejects.toThrow("download limit");
    expect(cancel).toHaveBeenCalled();
  });
});
