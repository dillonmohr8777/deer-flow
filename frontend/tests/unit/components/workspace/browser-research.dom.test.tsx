import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { type PropsWithChildren } from "react";

const mocks = rs.hoisted(() => ({
  user: { id: "owner-one", permissions: ["runs:create", "runs:cancel"] },
  status: rs.fn(),
  list: rs.fn(),
  read: rs.fn(),
  create: rs.fn(),
  cancel: rs.fn(),
  screenshot: rs.fn(),
  handOff: rs.fn(),
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: mocks.user }),
}));
rs.mock("@/components/workspace/workspace-container", () => ({
  WorkspaceContainer: ({ children }: PropsWithChildren) => (
    <div>{children}</div>
  ),
  WorkspaceHeader: () => <div />,
  WorkspaceBody: ({ children }: PropsWithChildren) => <main>{children}</main>,
}));
rs.mock("@/core/browserbase/api", () => ({
  getBrowserbaseStatus: mocks.status,
  listBrowserResearch: mocks.list,
  getBrowserResearch: mocks.read,
  createBrowserResearch: mocks.create,
  cancelBrowserResearch: mocks.cancel,
  loadBrowserResearchScreenshot: mocks.screenshot,
  handOffResearchDownload: mocks.handOff,
  isBrowserResearchBusy: (status: string) =>
    ["queued", "running"].includes(status),
}));

import { BrowserResearchWorkspace } from "@/components/workspace/browser-research";
import {
  type BrowserResearch,
  type BrowserbaseStatus,
} from "@/core/browserbase/api";

const STATUS: BrowserbaseStatus = {
  owner_scope: "scope-one",
  configured: true,
  available: true,
  reason: null,
  browser_minutes: null,
  monthly_minute_limit: null,
  remaining_minutes: null,
  mode: "public_read_only_snapshot",
  limits: {
    max_pages: 3,
    session_timeout_seconds: 180,
    max_sessions_per_owner: 1,
  },
};
const DETAIL: BrowserResearch = {
  id: "local-run",
  title: "Official docs",
  status: "completed",
  created_at: "2026-09-29T23:00:00Z",
  updated_at: "2026-09-29T23:00:01Z",
  last_error: null,
  urls: ["https://developers.openai.com/api/docs/"],
  pages: [
    {
      index: 0,
      url: "https://developers.openai.com/api/docs/",
      final_url: "https://developers.openai.com/api/docs/",
      title: "OpenAI docs",
      text: "<script>unsafe()</script> Actual captured words.",
      content_type: "text/html",
      screenshot_url: "/api/browserbase/research/local-run/pages/0/screenshot",
      source_mode: "public_read_only_snapshot",
    },
  ],
  session_id: "provider-session",
  replay_url: null,
  session_closed: true,
  usage: { browser_minutes: null, elapsed_seconds: 1, cost_usd: null },
};
const clients: QueryClient[] = [];
function Wrapper({ children }: PropsWithChildren) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
async function fillAndSubmit() {
  await screen.findByText("Remaining browser minutes unavailable.");
  fireEvent.change(screen.getByLabelText("Public HTTPS URLs, one per line"), {
    target: { value: "https://developers.openai.com/api/docs/" },
  });
  const button = screen.getByRole("button", {
    name: "Capture pages",
  });
  await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
  fireEvent.click(button);
}
beforeEach(() => {
  mocks.user = { id: "owner-one", permissions: ["runs:create", "runs:cancel"] };
  Object.values(mocks).forEach((mock) => {
    if (typeof mock === "function") mock.mockReset();
  });
  mocks.status.mockResolvedValue(STATUS);
  mocks.list.mockResolvedValue({ data: [] });
  mocks.read.mockResolvedValue(DETAIL);
  mocks.create.mockResolvedValue(DETAIL);
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
});

describe("Browser research workspace", () => {
  it("fences a previous workspace's late capture even when the actor ID stays the same", async () => {
    let resolveAdmission: (data: BrowserResearch) => void = () => undefined;
    mocks.create.mockImplementation(
      () =>
        new Promise<BrowserResearch>((resolve) => {
          resolveAdmission = resolve;
        }),
    );
    render(<BrowserResearchWorkspace />, { wrapper: Wrapper });
    await fillAndSubmit();
    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    mocks.status.mockResolvedValue({ ...STATUS, owner_scope: "scope-two" });
    fireEvent.click(
      screen.getByRole("button", { name: "Refresh saved captures" }),
    );
    await waitFor(() =>
      expect(
        mocks.list.mock.calls.some((call) => call[0] === "scope-two"),
      ).toBe(true),
    );
    resolveAdmission(DETAIL);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Capture pages" }),
      ).toBeDefined(),
    );
    expect(screen.queryByText(/page saved/)).toBeNull();
    expect(mocks.read).not.toHaveBeenCalled();
    expect(mocks.handOff).not.toHaveBeenCalled();
  });
  it("drops a previous actor's late admission result when auth ownership changes", async () => {
    let resolveAdmission: (data: BrowserResearch) => void = () => undefined;
    mocks.create.mockImplementation(
      () =>
        new Promise<BrowserResearch>((resolve) => {
          resolveAdmission = resolve;
        }),
    );
    const { rerender } = render(<BrowserResearchWorkspace />, {
      wrapper: Wrapper,
    });
    await fillAndSubmit();
    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    mocks.user = {
      id: "owner-two",
      permissions: ["runs:create", "runs:cancel"],
    };
    rerender(<BrowserResearchWorkspace />);
    await waitFor(() =>
      expect(
        screen.getByLabelText<HTMLTextAreaElement>(
          "Public HTTPS URLs, one per line",
        ).value,
      ).toBe(""),
    );
    resolveAdmission(DETAIL);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Capture pages" }),
      ).toBeDefined(),
    );
    expect(screen.queryByText(/page saved/)).toBeNull();
    expect(mocks.handOff).not.toHaveBeenCalled();
    expect(mocks.read).not.toHaveBeenCalled();
  });
  it("does not dispatch when unavailable or the actor has read-only permissions", async () => {
    mocks.status.mockResolvedValue({
      ...STATUS,
      available: false,
      reason: "unverified_quota",
    });
    const { unmount } = render(<BrowserResearchWorkspace />, {
      wrapper: Wrapper,
    });
    await screen.findByText(
      "Browser minutes could not be checked, so captures are paused until they can be.",
    );
    expect(screen.queryByText("unverified_quota")).toBeNull();
    fireEvent.change(screen.getByLabelText("Public HTTPS URLs, one per line"), {
      target: { value: "https://openai.com" },
    });
    expect(
      screen
        .getByRole("button", { name: "Capture pages" })
        .hasAttribute("disabled"),
    ).toBe(true);
    expect(mocks.create).not.toHaveBeenCalled();
    unmount();
    mocks.user.permissions = [];
    mocks.status.mockResolvedValue(STATUS);
    render(<BrowserResearchWorkspace />, { wrapper: Wrapper });
    await screen.findByText("You have read-only access.");
    expect(
      screen
        .getByRole("button", { name: "Capture pages" })
        .hasAttribute("disabled"),
    ).toBe(true);
    expect(mocks.create).not.toHaveBeenCalled();
  });

  it("resumes persisted evidence as plain text and keeps unpriced usage unknown", async () => {
    mocks.list.mockResolvedValue({ data: [DETAIL] });
    render(<BrowserResearchWorkspace />, { wrapper: Wrapper });
    fireEvent.click(
      await screen.findByRole("button", { name: /^Official docs Captured/ }),
    );
    await screen.findByText(/1 page saved/);
    expect(screen.getByText(DETAIL.pages[0]!.text).textContent).toBe(
      DETAIL.pages[0]!.text,
    );
    expect(document.querySelector("script")).toBeNull();
    expect(screen.getByText("Not recorded")).toBeDefined();
    expect(screen.getByText("Not priced")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Download evidence" }));
    await waitFor(() =>
      expect(mocks.handOff).toHaveBeenCalledWith(
        expect.any(Blob),
        "browser-research-local-run.json",
      ),
    );
    expect(mocks.create).not.toHaveBeenCalled();
  });

  it("re-tapping the open capture never steals focus on a later refresh", async () => {
    mocks.list.mockResolvedValue({ data: [DETAIL] });
    render(<BrowserResearchWorkspace />, { wrapper: Wrapper });
    const row = await screen.findByRole("button", {
      name: /^Official docs Captured/,
    });
    fireEvent.click(row);
    const title = await screen.findByRole("heading", {
      level: 3,
      name: "Official docs",
    });
    await waitFor(() => expect(document.activeElement).toBe(title));
    // Re-tap the open capture, then go and type in the form.
    fireEvent.click(row);
    expect(document.activeElement).toBe(title);
    const field = screen.getByLabelText<HTMLTextAreaElement>(
      "Public HTTPS URLs, one per line",
    );
    field.focus();
    mocks.read.mockResolvedValue({
      ...DETAIL,
      updated_at: "2026-09-30T00:00:00Z",
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Refresh saved captures" }),
    );
    await waitFor(() =>
      expect(mocks.read.mock.calls.length).toBeGreaterThan(1),
    );
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(document.activeElement).toBe(field);
  });

  it("shows a rejected capture's reason inside the form", async () => {
    mocks.list.mockResolvedValue({ data: [{ ...DETAIL, id: "older" }] });
    mocks.create.mockRejectedValueOnce(new Error("owner_busy"));
    render(<BrowserResearchWorkspace />, { wrapper: Wrapper });
    await fillAndSubmit();
    const alert = await screen.findByText(
      /A capture is already queued or running\. Wait for it to finish\./,
    );
    expect(alert.closest("#capture-form")).not.toBeNull();
  });

  it("reuses the admission receipt after an unconfirmed transport failure", async () => {
    mocks.create
      .mockRejectedValueOnce(new Error("Connection lost"))
      .mockResolvedValueOnce(DETAIL);
    render(<BrowserResearchWorkspace />, { wrapper: Wrapper });
    await fillAndSubmit();
    await screen.findByText(/The request is unconfirmed/);
    expect(
      screen
        .getByLabelText("Public HTTPS URLs, one per line")
        .hasAttribute("disabled"),
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Retry same request" }));
    await screen.findByText(/1 page saved/);
    expect(mocks.create).toHaveBeenCalledTimes(2);
    expect(mocks.create.mock.calls[0]).toEqual(mocks.create.mock.calls[1]);
    expect(mocks.create.mock.calls[0]?.[1]).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("shows failed captures without claiming useful output and blocks parallel dispatch", async () => {
    mocks.list.mockResolvedValue({ data: [{ ...DETAIL, status: "running" }] });
    mocks.read.mockResolvedValue({
      ...DETAIL,
      status: "failed",
      pages: [],
      last_error: "public_destination_rejected",
    });
    render(<BrowserResearchWorkspace />, { wrapper: Wrapper });
    fireEvent.click(
      await screen.findByRole("button", { name: /^Official docs Working/ }),
    );
    await screen.findByText("No page evidence has been retrieved.");
    expect(screen.queryByText(/page saved/)).toBeNull();
    // Nothing to download is no button, not a disabled one; the stored code
    // reads as a sentence, never as public_destination_rejected.
    expect(
      screen.queryByRole("button", { name: "Download evidence" }),
    ).toBeNull();
    expect(screen.queryByText("public_destination_rejected")).toBeNull();
    expect(
      screen.getByText("The capture could not be completed."),
    ).toBeDefined();
    expect(
      screen
        .getByRole("button", { name: "Capture pages" })
        .hasAttribute("disabled"),
    ).toBe(true);
  });
});
