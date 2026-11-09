import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";

import { ClientInbox } from "@/components/workspace/inbox/client-inbox";

const mocks = rs.hoisted(() => ({
  user: { id: "synthetic-client", role: "client" },
  fetch: rs.fn(),
  push: rs.fn(),
}));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: mocks.user }),
}));
rs.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: () => false }));
rs.mock("@/components/workspace/workspace-container", () => ({
  WorkspaceContainer: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  WorkspaceBody: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  WorkspaceHeader: () => null,
}));

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
const base = {
  id: "synthetic-request",
  client_id: "synthetic-client-co",
  subject: "Synthetic monthly report",
  state: "needs_approval",
  revision: 2,
  publish_receipt: null as string | null,
};
const review = {
  approval_id: "synthetic-approval",
  revision: 2,
  message_id: "synthetic-draft",
  body: "Synthetic draft for the client to check",
  attachments: [],
};

let tier: "software" | "standard" | null;
let calls: { path: string; method: string; body: unknown }[];

function route(url: string, options?: RequestInit) {
  const path = new URL(url, "https://synthetic.invalid").pathname;
  const method = options?.method ?? "GET";
  calls.push({
    path,
    method,
    body: options?.body ? JSON.parse(options.body as string) : undefined,
  });
  const service = tier
    ? {
        tier,
        booking_url:
          tier === "software" ? "https://booking.example.test/team" : null,
      }
    : undefined;
  if (path === "/api/client-portal/clients") {
    return json({
      workspace_id: "synthetic-workspace",
      clients: [{ id: "synthetic-client-co", name: "Synthetic Co" }],
      can_review: false,
      can_draft: false,
      ...(service ? { service } : {}),
    });
  }
  const momo_href =
    tier === "standard" ? null : "/workspace/agents/momobot-max";
  if (path === "/api/client-portal/threads") {
    return json({ threads: [{ ...base, momo_href }], has_more: false });
  }
  const detail = {
    ...base,
    momo_href,
    messages: [],
    can_review: false,
    can_draft: false,
    ...(tier ? { service_tier: tier, review_reason: null } : {}),
    ...(tier === "software" ? { can_approve: true, review } : {}),
  };
  if (path.endsWith("/approve")) {
    return json({ ...detail, review: undefined, publish_receipt: "receipt" });
  }
  if (path.endsWith("/request-changes")) {
    return json({ ...detail, review: undefined, state: "pending" });
  }
  return json(detail);
}

async function openRequest() {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <ClientInbox />
    </QueryClientProvider>,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: /Synthetic monthly report/ }),
  );
}

describe("client inbox with service tiers", () => {
  beforeEach(() => {
    calls = [];
    mocks.fetch.mockImplementation((url: string, options?: RequestInit) =>
      Promise.resolve(route(url, options)),
    );
  });
  afterEach(() => {
    cleanup();
    mocks.fetch.mockReset();
  });

  it("lets a software-tier client approve the exact draft and book a call", async () => {
    tier = "software";
    await openRequest();
    expect(
      await screen.findByText("Synthetic draft for the client to check"),
    ).toBeTruthy();
    const book = screen.getByRole("link", {
      name: "Book a call with your team",
    });
    expect(book.getAttribute("href")).toBe("https://booking.example.test/team");
    expect(book.getAttribute("rel")).toContain("noopener");
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() =>
      expect(calls.some((call) => call.path.endsWith("/approve"))).toBe(true),
    );
    expect(calls.find((call) => call.path.endsWith("/approve"))?.body).toEqual({
      approval_id: "synthetic-approval",
      expected_revision: 2,
    });
  });

  it("sends the client's change notes for the same draft", async () => {
    tier = "software";
    await openRequest();
    fireEvent.click(
      await screen.findByRole("button", { name: "Ask for changes" }),
    );
    const send = screen.getByRole("button", { name: "Send notes to my team" });
    expect((send as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("What should change?"), {
      target: { value: "Use the new logo" },
    });
    fireEvent.click(send);
    await waitFor(() =>
      expect(
        calls.find((call) => call.path.endsWith("/request-changes"))?.body,
      ).toEqual({
        approval_id: "synthetic-approval",
        expected_revision: 2,
        note: "Use the new logo",
      }),
    );
  });

  it("shows today's inbox when tiers are off: no approval, no booking link", async () => {
    tier = null;
    await openRequest();
    expect(
      await screen.findByRole("button", { name: "Talk to your Momo" }),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(
      screen.queryByRole("link", { name: "Book a call with your team" }),
    ).toBeNull();
  });

  it("hides Momo chat from a standard-tier client", async () => {
    tier = "standard";
    await openRequest();
    expect(
      await screen.findByRole("heading", { name: "Synthetic monthly report" }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Talk to your Momo" }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });
});
