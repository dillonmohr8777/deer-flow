import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

import {
  FirstLoginGate,
  type OnboardingState,
} from "@/components/workspace/onboarding-flow";
import { I18nProvider } from "@/core/i18n/context";

function Gate() {
  return (
    <QueryClientProvider client={new QueryClient()}>
      <I18nProvider initialLocale="en-US">
        <FirstLoginGate />
      </I18nProvider>
    </QueryClientProvider>
  );
}

const mocks = rs.hoisted(() => ({
  user: { id: "alice", system_role: "user" } as {
    id: string;
    system_role: string;
  },
  fetch: rs.fn(),
  connectChannelProvider: rs.fn(),
  setSettings: rs.fn(),
  selectWorkspace: rs.fn(),
  workspaceId: null as string | null,
  workspaceLoaded: true,
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: mocks.user }),
}));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: () => false }));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));
rs.mock("@/core/channels/api", () => ({
  connectChannelProvider: mocks.connectChannelProvider,
}));
rs.mock("@/core/settings", () => ({
  useLocalSettings: () => [{}, mocks.setSettings],
}));
rs.mock("@/core/workspaces/hooks", () => ({
  useWorkspaceSelection: () => ({
    data: mocks.workspaceLoaded
      ? { active_workspace_id: mocks.workspaceId }
      : undefined,
    busy: false,
    isLoading: false,
    selectWorkspace: mocks.selectWorkspace,
  }),
}));
rs.mock("@/components/workspace/experience-mode-chooser", () => ({
  ExperienceModeChooser: () => <p>old chooser</p>,
}));

const BASE: OnboardingState = {
  required: true,
  profile_saved: false,
  tools_saved: false,
  role: "Account manager",
  team: "Paid media",
  profile_found: true,
  clients: ["Example Co"],
  tools: ["slack"],
  other: "",
  catalog: [
    { id: "slack", label: "Slack", group: "Most used", pinned: true },
    { id: "gmail", label: "Gmail", group: "Most used", pinned: true },
    { id: "notion", label: "Notion", group: "Knowledge", pinned: false },
    { id: "github", label: "GitHub", group: "Development", pinned: false },
  ],
  connections: [],
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

type Call = { path: string; method: string; body: unknown };
function calls(): Call[] {
  return mocks.fetch.mock.calls.map(([path, init]) => ({
    path: String(path),
    method: (init as RequestInit | undefined)?.method ?? "GET",
    body:
      typeof (init as RequestInit | undefined)?.body === "string"
        ? JSON.parse((init as RequestInit).body as string)
        : undefined,
  }));
}

function serve(state: OnboardingState, toolkits?: unknown[]) {
  let current = state;
  mocks.fetch.mockImplementation(
    async (path: string, init: RequestInit | undefined) => {
      const method = init?.method ?? "GET";
      if (path.endsWith("/api/integrations/status")) {
        // Servers without personal connections answer 404.
        return toolkits ? json({ toolkits }) : json({}, 404);
      }
      if (path.endsWith("/tools")) {
        current = {
          ...current,
          connections: [
            {
              id: "slack",
              label: "Slack",
              status: "pending",
              available: true,
            },
            {
              id: "gmail",
              label: "Gmail",
              status: "pending",
              available: false,
            },
          ],
        };
      } else if (path.endsWith("/connections/gmail")) {
        const status = JSON.parse(init?.body as string).status as
          | "requested"
          | "skipped";
        current = {
          ...current,
          connections: current.connections.map((tool) =>
            tool.id === "gmail" ? { ...tool, status } : tool,
          ),
        };
      } else if (path.endsWith("/complete")) {
        current = { ...current, required: false };
      }
      return method === "GET" || path.includes("onboarding")
        ? json(current)
        : json({}, 404);
    },
  );
}

beforeEach(() => {
  mocks.user = { id: "alice", system_role: "user" };
  mocks.fetch.mockReset();
  mocks.connectChannelProvider.mockReset();
  mocks.setSettings.mockReset();
  mocks.selectWorkspace.mockReset();
  mocks.selectWorkspace.mockResolvedValue(undefined);
  mocks.workspaceId = null;
  mocks.workspaceLoaded = true;
});
afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

describe("first-login onboarding", () => {
  it("holds the gate on a failed or invalid read and retries the same account", async () => {
    serve(BASE);
    mocks.fetch
      .mockResolvedValueOnce(json({}, 500))
      .mockResolvedValueOnce(json({}));
    render(<Gate />);

    await screen.findByRole("alert");
    expect(screen.queryByText("old chooser")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(
        screen
          .getByRole("button", { name: "Try again" })
          .hasAttribute("disabled"),
      ).toBe(false),
    );
    expect(screen.queryByText("old chooser")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByDisplayValue("Account manager")).toBeTruthy();
    const init = mocks.fetch.mock.calls[2]![1] as RequestInit;
    expect(init.headers).toMatchObject({ "X-Expected-User-Id": "alice" });
  });

  it("times out a stalled status read and permits retry", async () => {
    const timeout = new AbortController();
    const timeoutSpy = rs
      .spyOn(AbortSignal, "timeout")
      .mockReturnValue(timeout.signal);
    serve(BASE);
    mocks.fetch.mockImplementationOnce(
      (_path: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          init.signal?.addEventListener("abort", () =>
            reject(new Error("aborted")),
          );
        }),
    );
    render(<Gate />);
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(timeoutSpy).toHaveBeenCalledWith(15000);
    await act(async () => timeout.abort());
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByText("old chooser")).toBeNull();
    timeoutSpy.mockRestore();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByDisplayValue("Account manager")).toBeTruthy();
  });

  it("cannot be dismissed before role and tools are saved", async () => {
    serve(BASE);
    render(<Gate />);
    const role = await screen.findByDisplayValue("Account manager");
    expect(screen.getByText(/Example Co/)).toBeTruthy();
    fireEvent.keyDown(document.activeElement ?? document.body, {
      key: "Escape",
    });
    expect(screen.getByDisplayValue("Account manager")).toBe(role);
    expect(screen.queryByRole("button", { name: /close/i })).toBeNull();
    expect(screen.queryByText(/^skip$/i)).toBeNull();
    fireEvent.change(role, { target: { value: "" } });
    expect(
      screen.getByRole("button", { name: "Continue" }).hasAttribute("disabled"),
    ).toBe(true);
  });

  it("walks the steps, uses the existing Slack connect, and ends in easy mode", async () => {
    serve(BASE);
    mocks.connectChannelProvider.mockResolvedValue({
      provider: "slack",
      mode: "binding_code",
      code: "ABC123",
      instruction: "DM ABC123 to MomoBot in Slack",
      expires_in: 600,
    });
    render(<Gate />);
    fireEvent.click(await screen.findByRole("button", { name: "Continue" }));
    fireEvent.click(await screen.findByLabelText("Gmail"));
    // The whole plugin catalog is offered, grouped, pinned tools first, and searchable.
    const legends = [...document.querySelectorAll("legend")].map(
      (node) => node.textContent,
    );
    expect(legends).toEqual(["Most used", "Knowledge", "Development"]);
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "git" },
    });
    expect(screen.queryByLabelText("Notion")).toBeNull();
    expect(screen.getByLabelText("GitHub")).toBeTruthy();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByText("Coming soon")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Link Slack DMs" }));
    expect(
      await screen.findByText("DM ABC123 to MomoBot in Slack"),
    ).toBeTruthy();
    expect(mocks.connectChannelProvider).toHaveBeenCalledWith("slack");

    const gmailRow = screen.getByText("Gmail").closest("li")!;
    fireEvent.click(gmailRow.querySelector("button:not([disabled])")!);
    await waitFor(() => expect(screen.getByText("Requested")).toBeTruthy());
    fireEvent.click(
      screen.getByRole("button", { name: /Finish and start in Easy mode/ }),
    );
    await waitFor(() =>
      expect(mocks.setSettings).toHaveBeenCalledWith("context", {
        experience_mode: "easy",
        mode: "flash",
      }),
    );

    const sent = calls().filter((call) => call.method !== "GET");
    expect(sent.map((call) => [call.method, call.path])).toEqual([
      ["PUT", "/api/v1/auth/onboarding/profile"],
      ["PUT", "/api/v1/auth/onboarding/tools"],
      ["POST", "/api/v1/auth/onboarding/connections/gmail"],
      ["POST", "/api/v1/auth/onboarding/complete"],
    ]);
    expect(sent[0]!.body).toEqual({
      role: "Account manager",
      team: "Paid media",
    });
    expect(sent[1]!.body).toEqual({ tools: ["slack", "gmail"], other: "" });
    expect(sent[2]!.body).toEqual({ status: "requested" });
    await waitFor(() => expect(screen.queryByText("Gmail")).toBeNull());
  });

  it("resumes at the connect step after a reload", async () => {
    serve({
      ...BASE,
      profile_saved: true,
      tools_saved: true,
      connections: [
        { id: "github", label: "GitHub", status: "shared", available: true },
      ],
    });
    render(<Gate />);
    expect(await screen.findByText("Connect your tools")).toBeTruthy();
    expect(screen.getByText("Ready for everyone")).toBeTruthy();
  });

  it("ignores completion arriving after the onboarding view unmounts", async () => {
    const resumed: OnboardingState = {
      ...BASE,
      profile_saved: true,
      tools_saved: true,
    };
    let resolveCompletion!: (response: Response) => void;
    mocks.fetch.mockImplementation((path: string) => {
      if (path.endsWith("/complete")) {
        return new Promise((resolve) => {
          resolveCompletion = resolve;
        });
      }
      return Promise.resolve(
        path.endsWith("/api/integrations/status")
          ? json({}, 404)
          : json(resumed),
      );
    });
    const view = render(<Gate />);
    fireEvent.click(
      await screen.findByRole("button", { name: /Finish and start/ }),
    );
    const call = mocks.fetch.mock.calls.find(([path]) =>
      String(path).endsWith("/complete"),
    )!;
    const signal = (call[1] as RequestInit).signal!;
    view.unmount();
    expect(signal.aborted).toBe(true);
    await act(async () =>
      resolveCompletion(json({ ...resumed, required: false })),
    );
    expect(mocks.setSettings).not.toHaveBeenCalled();
  });

  it("does not close or select Easy when the server still requires onboarding", async () => {
    const resumed = { ...BASE, profile_saved: true, tools_saved: true };
    mocks.fetch.mockImplementation((path: string) =>
      Promise.resolve(
        path.endsWith("/api/integrations/status")
          ? json({}, 404)
          : json(resumed),
      ),
    );
    render(<Gate />);
    fireEvent.click(
      await screen.findByRole("button", { name: /Finish and start/ }),
    );
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(mocks.setSettings).not.toHaveBeenCalled();
  });

  it("offers a real Connect for tools with a personal connection", async () => {
    serve(
      {
        ...BASE,
        profile_saved: true,
        tools_saved: true,
        connections: [
          { id: "gmail", label: "Gmail", status: "pending", available: true },
          {
            id: "google_calendar",
            label: "Google Calendar",
            status: "pending",
            available: true,
          },
          {
            id: "notion",
            label: "Notion",
            status: "pending",
            available: false,
          },
        ],
      },
      [
        { toolkit: "gmail", connected: false, connectable: true, reason: null },
        {
          toolkit: "googlecalendar",
          connected: true,
          connectable: false,
          reason: null,
        },
      ],
    );
    render(<Gate />);
    expect(
      await screen.findByRole("button", { name: "Connect Gmail" }),
    ).toBeTruthy();
    const gmailRow = screen.getByText("Gmail").closest("li")!;
    expect(gmailRow.textContent).not.toContain("Request access");
    fireEvent.click(within(gmailRow).getByRole("button", { name: "Skip" }));
    await waitFor(() => expect(gmailRow.textContent).toContain("Skipped"));
    expect(
      calls().find((call) => call.path.endsWith("/connections/gmail"))?.body,
    ).toEqual({ status: "skipped" });
    expect(
      within(gmailRow).getByRole("button", { name: "Connect Gmail" }),
    ).toBeTruthy();
    const calendarRow = screen.getByText("Google Calendar").closest("li")!;
    expect(calendarRow.textContent).toContain("Connected");
    // Tools without a personal connection keep the request path.
    const notionRow = screen.getByText("Notion").closest("li")!;
    expect(notionRow.textContent).toContain("Request access");
  });

  it("hands Slack setup to the private workspace and never connects from an unknown scope", async () => {
    const resumed = {
      ...BASE,
      profile_saved: true,
      tools_saved: true,
      connections: [
        {
          id: "slack",
          label: "Slack",
          status: "pending" as const,
          available: true,
        },
      ],
    };
    mocks.workspaceId = "shared";
    serve(resumed);
    render(<Gate />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Link Slack DMs" }),
    );
    await waitFor(() =>
      expect(mocks.selectWorkspace).toHaveBeenCalledWith(null),
    );
    expect(mocks.connectChannelProvider).not.toHaveBeenCalled();
    cleanup();

    mocks.workspaceLoaded = false;
    render(<Gate />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Link Slack DMs" }),
    );
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(mocks.connectChannelProvider).not.toHaveBeenCalled();
  });

  it("keeps a long connection list in a viewport-bounded scrollable dialog", async () => {
    serve({
      ...BASE,
      profile_saved: true,
      tools_saved: true,
      connections: Array.from({ length: 20 }, (_, index) => ({
        id: `tool-${index}`,
        label: `Tool ${index}`,
        status: "pending" as const,
        available: false,
      })),
    });
    render(<Gate />);
    await screen.findByText("Tool 19");
    const dialog = screen.getByRole("dialog");
    expect(dialog.className).toContain("max-h-[calc(100dvh-2rem)]");
    expect(dialog.className).toContain("overflow-y-auto");
    expect(
      within(dialog).getByRole("button", { name: /Finish and start/ }),
    ).toBeTruthy();
  });

  it("keeps the old chooser for clients and finished accounts", async () => {
    mocks.user = { id: "carol", system_role: "client" };
    render(<Gate />);
    expect(screen.getByText("old chooser")).toBeTruthy();
    expect(mocks.fetch).not.toHaveBeenCalled();
    cleanup();
    mocks.user = { id: "alice", system_role: "user" };
    serve({ ...BASE, required: false });
    render(<Gate />);
    expect(await screen.findByText("old chooser")).toBeTruthy();
  });
});
