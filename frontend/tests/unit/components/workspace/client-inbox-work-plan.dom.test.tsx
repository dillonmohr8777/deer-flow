import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import { ClientInbox } from "@/components/workspace/inbox/client-inbox";

const mocks = rs.hoisted(() => ({ fetch: rs.fn(), push: rs.fn() }));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "synthetic-contact", role: "user" } }),
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
rs.mock("@/components/workspace/inbox/client-context-panel", () => ({
  ClientContextPanel: () => null,
}));

const client = { id: "synthetic-client", name: "Synthetic client" };
const conversation = {
  id: "synthetic-request",
  client_id: client.id,
  subject: "Synthetic contact request",
  state: "pending",
  revision: 42,
  publish_receipt: null,
};
const response = (body: unknown) =>
  new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
  });
let queryClient: QueryClient;

describe("ClientInbox internal work plan contact boundary", () => {
  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    mocks.fetch.mockReset();
  });
  afterEach(() => {
    cleanup();
    queryClient.clear();
  });

  for (const rosterCanDraft of [false, true]) {
    it(`does not render or fetch a work plan for a nonstaff request (roster can_draft=${rosterCanDraft})`, async () => {
      mocks.fetch.mockImplementation(async (input: string) => {
        const url = new URL(input, "https://synthetic.invalid");
        const path = url.pathname.replace("/api/client-portal", "");
        if (path === "/clients")
          return response({
            workspace_id: "synthetic-workspace",
            clients: [client],
            can_draft: rosterCanDraft,
            can_review: false,
          });
        if (path === "/threads")
          return response({ threads: [conversation], has_more: false });
        if (path === `/threads/${conversation.id}`)
          return response({
            ...conversation,
            can_draft: false,
            can_review: false,
            messages: [
              {
                id: "synthetic-message",
                author: "Synthetic contact",
                body: "Synthetic public timeline body",
                created_at: "2026-10-24T12:00:00Z",
                attachments: [],
              },
            ],
            draft: null,
          });
        if (path.endsWith("/context"))
          return response({
            schema: "client_operating_context.v1",
            workspace_id: "synthetic-workspace",
            client,
            current_request: { id: conversation.id },
            requests: { items: [], has_more: false },
          });
        throw new Error(`Unexpected synthetic API request: ${path}`);
      });
      render(
        <QueryClientProvider client={queryClient}>
          <ClientInbox />
        </QueryClientProvider>,
      );
      fireEvent.click(
        await screen.findByRole("button", {
          name: /Synthetic contact request/,
        }),
      );
      await screen.findByText("Synthetic public timeline body");
      expect(screen.queryByLabelText("Internal work plan")).toBeNull();
      expect(
        screen.queryByRole("button", { name: "Save work plan" }),
      ).toBeNull();
      expect(
        mocks.fetch.mock.calls.filter(([url]) =>
          String(url).includes("/work-plan"),
        ),
      ).toEqual([]);
    });
  }
});
