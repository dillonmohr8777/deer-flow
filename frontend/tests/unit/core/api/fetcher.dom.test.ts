import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";

import { getAPIClient } from "@/core/api/api-client";
import { fetch as apiFetch, setLoggingOut } from "@/core/api/fetcher";

describe("api fetcher unauthorized redirect", () => {
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    globalThis.fetch = rs.fn(
      async () => new Response("", { status: 401 }),
    ) as unknown as typeof globalThis.fetch;
  });

  afterEach(() => {
    setLoggingOut(false);
    globalThis.fetch = originalFetch;
  });

  it("returns the caller to the full URL, query string included", async () => {
    window.history.replaceState(
      {},
      "",
      "/artifacts/view?path=%2Fmnt%2Fuser-data%2Foutputs%2Freport.md&thread_id=t-1",
    );

    // The wrapper redirects and then throws UnauthorizedError; the redirect
    // target is what this test is about.
    await expect(
      apiFetch("/api/threads/t-1/artifacts/mnt/user-data/outputs/report.md"),
    ).rejects.toThrow();

    expect(window.location.href).toContain("/login?next=");
    const next = new URL(
      window.location.href,
      "http://localhost",
    ).searchParams.get("next");
    expect(next).toBe(
      "/artifacts/view?path=%2Fmnt%2Fuser-data%2Foutputs%2Freport.md&thread_id=t-1",
    );
  });

  it("does not redirect a 401 while logout is in progress", async () => {
    window.history.replaceState(
      {},
      "",
      "/workspace/chats/new?settings=security",
    );
    const currentUrl = window.location.href;
    setLoggingOut(true);

    await expect(apiFetch("/api/threads")).rejects.toThrow();

    expect(window.location.href).toBe(currentUrl);
  });

  it("returns SDK requests to sign-in without retrying an expired session", async () => {
    window.history.replaceState(
      {},
      "",
      "/workspace/chats/new?settings=security",
    );

    await expect(getAPIClient(true).threads.search({})).rejects.toThrow();

    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
    expect(window.location.pathname).toBe("/login");
    expect(new URL(window.location.href).searchParams.get("next")).toBe(
      "/workspace/chats/new?settings=security",
    );
  });
});
