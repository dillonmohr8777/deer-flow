import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import {
  FirstLoginGate,
  type OnboardingState,
} from "@/components/workspace/onboarding-flow";
import { I18nProvider } from "@/core/i18n/context";

function Gate() {
  return (
    <I18nProvider initialLocale="en-US">
      <FirstLoginGate />
    </I18nProvider>
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
rs.mock("@/components/workspace/experience-mode-chooser", () => ({
  ExperienceModeChooser: () => <p>old chooser</p>,
}));

const BASE: OnboardingState = {
  required: true,
  role: "Account manager",
  team: "Paid media",
  profile_found: true,
  clients: ["Example Co"],
  tools: ["slack"],
  other: "",
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

function serve(state: OnboardingState) {
  let current = state;
  mocks.fetch.mockImplementation(
    async (path: string, init: RequestInit | undefined) => {
      const method = init?.method ?? "GET";
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
        current = {
          ...current,
          connections: current.connections.map((tool) =>
            tool.id === "gmail" ? { ...tool, status: "requested" } : tool,
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
});
afterEach(() => cleanup());

describe("first-login onboarding", () => {
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
