import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";

import { finishInPopup } from "@/core/integrations/composio/api";

rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));

/** A same-origin popup whose page we script: path plus body text. */
function fakePopup() {
  const page = { path: "/", text: "", ready: "complete" };
  const popup = {
    closed: false,
    close() {
      popup.closed = true;
    },
    location: {
      set href(url: string) {
        page.path = new URL(url, "https://momo.test").pathname;
        page.text = "";
      },
      get pathname() {
        return page.path;
      },
    },
    document: {
      get readyState() {
        return page.ready;
      },
      get body() {
        return { innerText: page.text };
      },
    },
  };
  return { popup: popup as unknown as Window & { closed: boolean }, page };
}

const GMAIL = { handle: "gmail_handle_0001", toolkit: "gmail" };

beforeEach(() => {
  rs.useFakeTimers();
});
afterEach(() => {
  rs.useRealTimers();
});

describe("finishInPopup", () => {
  it("resolves only for its own handle and toolkit", async () => {
    const { popup, page } = fakePopup();
    const done = finishInPopup(popup, GMAIL);
    page.path = "/api/integrations/callback";
    page.text = JSON.stringify({
      handle: GMAIL.handle,
      toolkit: "gmail",
      status: "connected",
      retry: { state: "not_requested" },
    });
    await rs.advanceTimersByTimeAsync(600);
    await expect(done).resolves.toMatchObject({ toolkit: "gmail" });
    expect(popup.closed).toBe(true);
  });

  it("rejects another attempt's callback instead of claiming it", async () => {
    const { popup, page } = fakePopup();
    const done = finishInPopup(popup, GMAIL);
    page.path = "/api/integrations/callback";
    page.text = JSON.stringify({
      handle: "slack_handle_0002",
      toolkit: "slack",
      status: "connected",
      retry: { state: "not_requested" },
    });
    const outcome = done.catch((error: Error) => error.message);
    await rs.advanceTimersByTimeAsync(600);
    expect(await outcome).toBe("connect_result_mismatch");
  });

  it("finishes promptly when /open answers with a consumed or expired handle", async () => {
    const { popup, page } = fakePopup();
    const done = finishInPopup(popup, GMAIL);
    // The server answered the open itself; the provider was never reached.
    page.text = JSON.stringify({ detail: "connect_open_consumed" });
    const outcome = done.catch((error: Error) => error.message);
    await rs.advanceTimersByTimeAsync(600);
    expect(await outcome).toBe("connect_open_consumed");
    expect(popup.closed).toBe(true);
  });

  it("keeps waiting while /open is still redirecting", async () => {
    const { popup, page } = fakePopup();
    let settled = false;
    void finishInPopup(popup, GMAIL)
      .catch(() => undefined)
      .finally(() => {
        settled = true;
      });
    page.ready = "loading";
    await rs.advanceTimersByTimeAsync(5_000);
    expect(settled).toBe(false);
    popup.close();
    await rs.advanceTimersByTimeAsync(600);
    expect(settled).toBe(true);
  });
});
