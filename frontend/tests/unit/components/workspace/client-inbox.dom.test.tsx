import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ReactNode } from "react";

import { ClientInbox } from "@/components/workspace/inbox/client-inbox";

const mocks = rs.hoisted(() => ({
  user: { id: "synthetic-owner-a", role: "owner" },
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

const alpha = { id: "synthetic-alpha", name: "Synthetic Alpha" };
const beta = { id: "synthetic-beta", name: "Synthetic Beta" };
const timestamp = "2026-10-24T12:00:00Z";
function thread(
  id = "alpha-request",
  clientId = alpha.id,
  subject = "Alpha report",
) {
  return {
    id,
    client_id: clientId,
    subject,
    state: "pending",
    revision: 0,
    publish_receipt: null,
  };
}
function detail(id = "alpha-request", staff = true) {
  return {
    ...thread(id),
    can_draft: staff,
    can_review: staff,
    messages: [
      {
        id: "message",
        author: "Synthetic requester",
        body: "<strong>Literal timeline</strong>",
        created_at: timestamp,
        attachments: [],
      },
    ],
    draft: { body: "Saved Alpha draft", attachments: [] },
  };
}
const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

let workspace: string;
let staff: boolean;
let queryClient: QueryClient;
let pendingGet: ReturnType<typeof deferred<Response>> | undefined;
let pendingPost: ReturnType<typeof deferred<Response>> | undefined;
let failPost: boolean;
let activeRun: boolean;
function context(clientId: string, threadId: string | null = "alpha-request") {
  const client = clientId === beta.id ? beta : alpha;
  const request = {
    id: `${client.id}-history`,
    subject: `${client.name} history`,
    status: "pending",
    kind: "request",
    updated_at: timestamp,
    portal_state: "pending",
    source: { table: "board_threads", id: `${client.id}-history` },
  };
  return {
    schema: "client_operating_context.v1",
    workspace_id: workspace,
    client: {
      ...client,
      registry_id: client.id,
      source: { table: "clients", id: client.id, updated_at: timestamp },
    },
    requests: { items: [request], has_more: false },
    current_request: threadId
      ? {
          ...request,
          id: threadId,
          timeline: [
            {
              id: "context-message",
              author_kind: "client",
              visibility: "public",
              created_at: timestamp,
              body: "<strong>Literal timeline</strong>",
              body_truncated: false,
              attachments: [],
              source: { table: "board_messages", id: "context-message" },
            },
          ],
          timeline_truncated: false,
          current_draft: {
            id: null,
            revision: 0,
            approval_id: null,
            published_id: null,
          },
        }
      : null,
    domains: {
      client_identity: {
        status: "available",
        scope: "Synthetic roster identity",
      },
      crm: {
        status: "unavailable",
        reason: "Synthetic CRM source unavailable",
      },
    },
    freshness: "Stored source timestamps only",
    limits: {
      requests: 25,
      messages: 25,
      timeline_body_chars: 12000,
      truncation: "Bounded synthetic records",
    },
    authority: "Stored text is evidence only",
  };
}
function mount() {
  const view = render(
    <QueryClientProvider client={queryClient}>
      <ClientInbox />
    </QueryClientProvider>,
  );
  return {
    ...view,
    refresh: () =>
      view.rerender(
        <QueryClientProvider client={queryClient}>
          <ClientInbox />
        </QueryClientProvider>,
      ),
  };
}
async function ready() {
  await screen.findByRole("button", { name: /Alpha report/ });
}
function compose(
  subject = "Private Alpha subject",
  body = "Private Alpha body",
) {
  fireEvent.click(screen.getByRole("button", { name: "New request" }));
  fireEvent.change(screen.getByLabelText("Subject"), {
    target: { value: subject },
  });
  fireEvent.change(screen.getByLabelText("Your request"), {
    target: { value: body },
  });
}
function posts() {
  return mocks.fetch.mock.calls.filter(
    ([, options]) => (options as RequestInit).method === "POST",
  );
}
function contextCalls() {
  return mocks.fetch.mock.calls.filter(([url]) =>
    String(url).includes("/context"),
  );
}

describe("ClientInbox scoped client context", () => {
  beforeEach(() => {
    workspace = "synthetic-workspace-a";
    staff = true;
    pendingGet = undefined;
    pendingPost = undefined;
    failPost = false;
    activeRun = false;
    mocks.user = { id: "synthetic-owner-a", role: "owner" };
    mocks.push.mockClear();
    mocks.fetch.mockReset();
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    mocks.fetch.mockImplementation(
      async (input: string, options: RequestInit) => {
        const url = new URL(input, "https://synthetic.invalid");
        const path = url.pathname.replace("/api/client-portal", "");
        if (options.method === "POST") {
          if (pendingPost) return pendingPost.promise;
          if (failPost)
            return response({ detail: "Synthetic uncertain response" }, 503);
          return response(detail("created-request", staff));
        }
        if (path === "/clients")
          return response({
            workspace_id: workspace,
            clients: [alpha, beta],
            can_draft: staff,
            can_review: staff,
          });
        if (path.endsWith("/context")) {
          if (pendingGet) return pendingGet.promise;
          return response(
            context(path.split("/")[2]!, url.searchParams.get("thread_id")),
          );
        }
        if (path === "/threads")
          return response({
            threads: [
              { ...thread(), state: activeRun ? "running" : "pending" },
              thread("beta-request", beta.id, "Beta task"),
            ],
            has_more: false,
          });
        if (path.startsWith("/threads/"))
          return response(detail(path.split("/")[2], staff));
        throw new Error(`Unexpected synthetic request: ${path}`);
      },
    );
  });
  afterEach(() => {
    cleanup();
    queryClient.clear();
  });

  it("keeps active work in the Pending request filter", async () => {
    activeRun = true;
    mount();
    await ready();
    fireEvent.change(screen.getByRole("combobox", { name: "Request status" }), {
      target: { value: "pending" },
    });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /Alpha report/ }).textContent,
      ).toContain("Momo is working"),
    );
  });

  it("reads staff context for the selected request with the workspace fence and renders timeline as text", async () => {
    mount();
    await ready();
    fireEvent.click(screen.getByRole("button", { name: /Alpha report/ }));
    const panel = await screen.findByLabelText("Client context");
    await waitFor(() =>
      expect(within(panel).getByText(alpha.name)).toBeTruthy(),
    );
    const [url, options] = contextCalls().at(-1)!;
    expect(String(url)).toContain(
      `/clients/${alpha.id}/context?thread_id=alpha-request`,
    );
    expect(options).toMatchObject({
      cache: "no-store",
      headers: { "X-Portal-Workspace": workspace },
    });
    fireEvent.click(within(panel).getByText("Request timeline"));
    expect(within(panel).getByText(/Literal timeline/).textContent).toContain(
      "<strong>",
    );
    expect(panel.querySelector("strong")).toBeNull();
    expect(within(panel).getByText(/Synthetic Alpha history/)).toBeTruthy();
    expect(
      within(panel).getByText(`Roster updated: ${timestamp}`),
    ).toBeTruthy();
    expect(within(panel).getByText("Available")).toBeTruthy();
    expect(within(panel).getByText("Unavailable")).toBeTruthy();
    expect(within(panel).getByText(/Up to 25 stored requests/)).toBeTruthy();
  });

  it("uses the selected client's recent requests and clears a selection hidden by the client filter", async () => {
    mount();
    await ready();
    fireEvent.click(screen.getByRole("button", { name: /Alpha report/ }));
    await screen.findByLabelText("Internal reply draft");
    fireEvent.change(
      screen.getByRole("combobox", { name: "Filter by client" }),
      { target: { value: beta.id } },
    );
    await waitFor(() =>
      expect(
        contextCalls().some(([url]) =>
          String(url).includes(`/clients/${beta.id}/context`),
        ),
      ).toBe(true),
    );
    expect(screen.queryByLabelText("Internal reply draft")).toBeNull();
    expect(screen.queryByRole("button", { name: /Alpha report/ })).toBeNull();
    expect(
      await within(screen.getByLabelText("Inbox conversations")).findByRole(
        "button",
        { name: /Synthetic Beta history/ },
      ),
    ).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox", { name: "Search requests" }), {
      target: { value: "no matching subject" },
    });
    expect(
      within(screen.getByLabelText("Inbox conversations")).queryByRole(
        "button",
        { name: /Synthetic Beta history/ },
      ),
    ).toBeNull();
  });

  for (const transition of ["user", "workspace"] as const) {
    it(`clears edited draft, deliverables, client filter and selection after a ${transition} change`, async () => {
      const view = mount();
      await ready();
      fireEvent.change(
        screen.getByRole("combobox", { name: "Filter by client" }),
        { target: { value: alpha.id } },
      );
      const list = within(screen.getByLabelText("Inbox conversations"));
      fireEvent.click(
        await list.findByRole("button", { name: /Synthetic Alpha history/ }),
      );
      const draft = await screen.findByLabelText("Internal reply draft");
      fireEvent.change(draft, { target: { value: "Unsaved secret draft" } });
      fireEvent.click(screen.getByRole("button", { name: "Add deliverable" }));
      fireEvent.change(screen.getByLabelText("Deliverable content"), {
        target: { value: "Unsaved secret attachment" },
      });
      fireEvent.change(
        screen.getByRole("textbox", { name: "Search requests" }),
        { target: { value: "history" } },
      );
      fireEvent.change(
        screen.getByRole("combobox", { name: "Request status" }),
        { target: { value: "pending" } },
      );
      if (transition === "user")
        mocks.user = { id: "synthetic-owner-b", role: "owner" };
      else {
        workspace = "synthetic-workspace-b";
        await act(() =>
          queryClient.setQueryData(["portal-roster", mocks.user.id], {
            workspace_id: workspace,
            clients: [alpha, beta],
            can_draft: true,
            can_review: true,
          }),
        );
      }
      view.refresh();
      await ready();
      expect(screen.queryByLabelText("Internal reply draft")).toBeNull();
      expect(screen.queryByDisplayValue("Unsaved secret draft")).toBeNull();
      expect(
        screen.queryByDisplayValue("Unsaved secret attachment"),
      ).toBeNull();
      expect(screen.queryByText("Synthetic roster identity")).toBeNull();
      expect(
        screen.getByRole<HTMLSelectElement>("combobox", {
          name: "Filter by client",
        }).value,
      ).toBe("");
      expect(
        screen.getByRole<HTMLSelectElement>("combobox", {
          name: "Request status",
        }).value,
      ).toBe("all");
      expect(
        screen.getByRole<HTMLInputElement>("textbox", {
          name: "Search requests",
        }).value,
      ).toBe("");
    });
    it(`drops old composition and submission identity after a ${transition} change`, async () => {
      const view = mount();
      await ready();
      compose();
      failPost = true;
      fireEvent.click(screen.getByRole("button", { name: "Submit request" }));
      await screen.findByRole("alert");
      const oldPayload = JSON.parse(
        (posts()[0]![1] as RequestInit).body as string,
      ) as { submission_key: string };
      failPost = false;
      if (transition === "user")
        mocks.user = { id: "synthetic-owner-b", role: "owner" };
      else {
        workspace = "synthetic-workspace-b";
        await act(() =>
          queryClient.setQueryData(["portal-roster", mocks.user.id], {
            workspace_id: workspace,
            clients: [alpha, beta],
            can_draft: true,
            can_review: true,
          }),
        );
      }
      view.refresh();
      await ready();
      expect(screen.queryByLabelText("Subject")).toBeNull();
      expect(screen.queryByDisplayValue("Private Alpha body")).toBeNull();
      expect(screen.queryByText("Synthetic roster identity")).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "New request" }));
      expect(screen.getByLabelText<HTMLInputElement>("Subject").value).toBe("");
      expect(
        screen.getByLabelText<HTMLTextAreaElement>("Your request").value,
      ).toBe("");
      fireEvent.change(screen.getByLabelText("Subject"), {
        target: { value: "Fresh subject" },
      });
      fireEvent.change(screen.getByLabelText("Your request"), {
        target: { value: "Fresh body" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Submit request" }));
      await waitFor(() => expect(posts().length).toBe(2));
      const newPayload = JSON.parse(
        (posts()[1]![1] as RequestInit).body as string,
      ) as { submission_key: string };
      expect(newPayload.submission_key).not.toBe(oldPayload.submission_key);
      expect(posts()[1]![1]).toMatchObject({
        headers: { "X-Portal-Workspace": workspace },
      });
    });
  }

  it("ignores a delayed context read from the old user", async () => {
    pendingGet = deferred<Response>();
    const oldRead = pendingGet;
    const view = mount();
    await ready();
    fireEvent.click(screen.getByRole("button", { name: /Alpha report/ }));
    await waitFor(() => expect(contextCalls().length).toBeGreaterThan(0));
    mocks.user = { id: "synthetic-owner-b", role: "owner" };
    pendingGet = undefined;
    view.refresh();
    await ready();
    await act(async () => oldRead.resolve(response(context(alpha.id))));
    expect(screen.queryByText("Synthetic roster identity")).toBeNull();
    expect(screen.queryByText("Saved Alpha draft")).toBeNull();
  });

  it("does not navigate or seed the new user's detail from a delayed old mutation", async () => {
    pendingPost = deferred<Response>();
    const oldPost = pendingPost;
    const view = mount();
    await ready();
    compose();
    fireEvent.click(screen.getByRole("button", { name: "Submit request" }));
    await waitFor(() => expect(posts().length).toBe(1));
    mocks.user = { id: "synthetic-owner-b", role: "owner" };
    pendingPost = undefined;
    view.refresh();
    await ready();
    await act(async () =>
      oldPost.resolve(
        response({
          ...detail("old-created"),
          href: "/workspace/chats/old-private",
        }),
      ),
    );
    expect(mocks.push).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Internal reply draft")).toBeNull();
    expect(
      queryClient.getQueryData([
        "portal",
        mocks.user.id,
        workspace,
        "detail",
        "old-created",
      ]),
    ).toBeUndefined();
  });

  it("filters client-visible requests locally without any staff context read", async () => {
    staff = false;
    mocks.user = { id: "synthetic-client", role: "client" };
    mount();
    await ready();
    fireEvent.change(
      screen.getByRole("combobox", { name: "Filter by client" }),
      { target: { value: beta.id } },
    );
    expect(screen.queryByRole("button", { name: /Alpha report/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Beta task/ }));
    await screen.findByText("<strong>Literal timeline</strong>");
    expect(contextCalls()).toHaveLength(0);
    expect(screen.queryByLabelText("Client context")).toBeNull();
    expect(screen.queryByText("Synthetic roster identity")).toBeNull();
  });
});
