import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { ConnectButton } from "@/components/workspace/connections/connect-cards";

const mocks = rs.hoisted(() => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));

/** One scripted same-origin popup per window.open call. */
function scriptPopups(pages: { path: string; body: unknown }[]) {
  const opened: { closed: boolean }[] = [];
  rs.spyOn(window, "open").mockImplementation(() => {
    const page = pages[opened.length]!;
    const popup = {
      closed: false,
      close() {
        popup.closed = true;
      },
      location: {
        href: "",
        get pathname() {
          return page.path;
        },
      },
      document: {
        readyState: "complete",
        body: { innerText: JSON.stringify(page.body) },
      },
    };
    opened.push(popup);
    return popup as unknown as Window;
  });
  return opened;
}

function renderButton(handle: string | undefined, client: QueryClient) {
  return render(
    <QueryClientProvider client={client}>
      <ConnectButton toolkit="gmail" handle={handle} threadId="thread-1" />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
  mocks.fetch.mockReset();
});

describe("in-chat ConnectButton", () => {
  it("refreshes the chat's own run and history queries after a submitted retry", async () => {
    scriptPopups([
      {
        path: "/api/integrations/callback",
        body: {
          handle: "tool_handle_0001",
          toolkit: "gmail",
          status: "connected",
          retry: { state: "submitted", run_id: "r2", source_run_id: "r1" },
        },
      },
    ]);
    mocks.fetch.mockImplementation(async (url: string) =>
      url.includes("/runs/r1/events")
        ? new Response(
            JSON.stringify([
              {
                event_type: "composio.connected",
                content: { handle: "tool_handle_0001" },
              },
            ]),
          )
        : new Response("{}", { status: 404 }),
    );
    const client = new QueryClient();
    const invalidate = rs.spyOn(client, "invalidateQueries");
    renderButton("tool_handle_0001", client);
    fireEvent.click(screen.getByRole("button", { name: "Connect Gmail" }));
    expect(
      await screen.findByText(/MomoBot is finishing/, {}, { timeout: 3000 }),
    ).toBeTruthy();
    await waitFor(() => {
      const keys = invalidate.mock.calls.map(([filters]) =>
        JSON.stringify(filters?.queryKey),
      );
      expect(keys).toContain(JSON.stringify(["thread", "thread-1"]));
      expect(keys).toContain(JSON.stringify(["thread-messages", "thread-1"]));
    });
  });

  it("never reuses a consumed tool handle and asks for a fresh retry", async () => {
    const opened = scriptPopups([
      {
        path: "/api/integrations/connect/tool_handle_0001/open",
        body: { detail: "connect_open_consumed" },
      },
      { path: "/blank", body: "" },
    ]);
    mocks.fetch.mockImplementation(async (url: string, init?: RequestInit) =>
      url.endsWith("/api/integrations/connect") && init?.method === "POST"
        ? new Response(
            JSON.stringify({
              handle: "fresh_handle_0002",
              toolkit: "gmail",
              expires_at: "2026-10-24T04:00:00Z",
            }),
          )
        : new Response("{}", { status: 404 }),
    );
    renderButton("tool_handle_0001", new QueryClient());
    fireEvent.click(screen.getByRole("button", { name: "Connect Gmail" }));
    expect(
      await screen.findByText(
        /already used.*ask MomoBot to try that step again/,
        {},
        { timeout: 3000 },
      ),
    ).toBeTruthy();
    expect(opened[0]!.closed).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Connect Gmail" }));
    await waitFor(() =>
      expect(
        mocks.fetch.mock.calls.some(
          ([url, init]) =>
            String(url).endsWith("/api/integrations/connect") &&
            (init as RequestInit | undefined)?.method === "POST",
        ),
      ).toBe(true),
    );
    // A second popup, not the first one reused.
    expect(opened.length).toBe(2);
  });
});
