import { expect, test, type Page, type Route } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const at = (hours: number) =>
  new Date(Date.now() + hours * 3_600_000).toISOString();

const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

type Thread = {
  id: string;
  client_id: string | null;
  kind: string;
  status: string;
  subject: string;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
};

type Message = {
  id: string;
  thread_id: string;
  author_kind: string;
  author_user_id: string | null;
  body: string;
  created_at: string;
};

function thread(id: string, patch: Partial<Thread> = {}): Thread {
  return {
    id,
    client_id: "acme",
    kind: "ticket",
    status: "new",
    subject: `Thread ${id}`,
    created_by_user_id: "client-1",
    created_at: at(-4),
    updated_at: at(-4),
    ...patch,
  };
}

async function mockBoard(
  page: Page,
  {
    desk = true,
    threads = [],
    myClients,
    hideUnapprovedDraft = false,
    initialMessages = {},
  }: {
    desk?: boolean;
    threads?: Thread[];
    /** Clients the create-thread picker offers. Defaults to just Acme. */
    myClients?: { id: string; display_name: string }[];
    /**
     * Mirrors the backend's per-caller filter on
     * ``GET .../messages``: a client contact never sees a ``momo`` message
     * while the thread is ``drafted``, only once it's approved. An owner/
     * admin caller leaves this false and sees the draft immediately.
     */
    hideUnapprovedDraft?: boolean;
    /** Seeded message history, keyed by thread id. */
    initialMessages?: Record<string, Message[]>;
  } = {},
) {
  mockLangGraphAPI(page, { scheduledTasks: [] });

  const state = new Map<string, Thread>(threads.map((t) => [t.id, t]));
  const messages = new Map<string, Message[]>(
    Object.entries(initialMessages).map(([id, list]) => [id, [...list]]),
  );
  let nextMessageId = 1;

  await page.route("**/api/features", (route) =>
    route.fulfill(
      json({ agents_api: { enabled: true }, desk: { enabled: desk } }),
    ),
  );
  const clientRow = (id: string, display_name: string) => ({
    id,
    display_name,
    aliases: [],
    status: "active",
    email_domains: [],
    slack_channel_ids: [],
    registry_id: null,
    notes: "",
    created_at: at(-200),
    updated_at: at(-200),
    assignments: [],
    project_count: 0,
  });

  await page.route("**/api/clients", (route) =>
    route.fulfill(json({ clients: [clientRow("acme", "Acme Landscaping")] })),
  );
  await page.route("**/api/clients/mine", (route) =>
    route.fulfill(
      json({
        clients: (
          myClients ?? [{ id: "acme", display_name: "Acme Landscaping" }]
        ).map((c) => clientRow(c.id, c.display_name)),
      }),
    ),
  );

  let nextThreadId = threads.length + 1;

  await page.route("**/api/board/threads", async (route: Route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON() as {
        client_id: string;
        kind: string;
        subject: string;
      };
      const row = thread(`t${nextThreadId++}`, {
        client_id: body.client_id,
        kind: body.kind,
        subject: body.subject,
        status: "new",
      });
      state.set(row.id, row);
      await route.fulfill({ ...json(row), status: 201 });
      return;
    }
    if (route.request().method() !== "GET") return route.fallback();
    const url = new URL(route.request().url());
    const status = url.searchParams.get("status");
    const list = [...state.values()].filter(
      (t) => !status || t.status === status,
    );
    await route.fulfill(json({ threads: list }));
  });

  await page.route(/\/api\/board\/threads\/([^/]+)$/, async (route: Route) => {
    const id = /threads\/([^/?]+)/.exec(route.request().url())![1]!;
    const row = state.get(id);
    if (!row) return route.fulfill({ status: 404, body: "{}" });
    await route.fulfill(json(row));
  });

  await page.route(
    /\/api\/board\/threads\/([^/]+)\/messages$/,
    async (route: Route) => {
      const id = /threads\/([^/]+)\/messages/.exec(route.request().url())![1]!;
      let list = messages.get(id) ?? [];
      if (hideUnapprovedDraft && state.get(id)?.status === "drafted") {
        list = list.filter((m) => m.author_kind !== "momo");
      }
      await route.fulfill(json({ messages: list }));
    },
  );

  const addMessage = (id: string, authorKind: string, body: string) => {
    const list = messages.get(id) ?? [];
    const message: Message = {
      id: `msg-${nextMessageId++}`,
      thread_id: id,
      author_kind: authorKind,
      author_user_id: null,
      body,
      created_at: new Date().toISOString(),
    };
    list.push(message);
    messages.set(id, list);
  };

  await page.route(
    /\/api\/board\/threads\/([^/]+)\/draft$/,
    async (route: Route) => {
      const id = /threads\/([^/]+)\/draft/.exec(route.request().url())![1]!;
      const body = route.request().postDataJSON() as { body: string };
      addMessage(id, "momo", body.body);
      const row = { ...state.get(id)!, status: "drafted" };
      state.set(id, row);
      await route.fulfill(json(row));
    },
  );

  await page.route(
    /\/api\/board\/threads\/([^/]+)\/approve$/,
    async (route: Route) => {
      const id = /threads\/([^/]+)\/approve/.exec(route.request().url())![1]!;
      const row = { ...state.get(id)!, status: "approved" };
      state.set(id, row);
      await route.fulfill(json(row));
    },
  );

  await page.route(
    /\/api\/board\/threads\/([^/]+)\/reply$/,
    async (route: Route) => {
      const id = /threads\/([^/]+)\/reply/.exec(route.request().url())![1]!;
      const body = route.request().postDataJSON() as { body: string };
      addMessage(id, "owner", body.body);
      const row = { ...state.get(id)!, status: "replied" };
      state.set(id, row);
      await route.fulfill(json(row));
    },
  );
}

test.describe("Board, the Momo Board thread queue", () => {
  test("walks a thread through draft, approve and send", async ({ page }) => {
    await mockBoard(page, {
      threads: [thread("t1", { subject: "Site is down", kind: "ticket" })],
    });
    await page.goto("/workspace/board");

    const board = page.getByTestId("board");
    await expect(
      board.getByRole("heading", { level: 1, name: "Board" }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(board.getByText("Site is down")).toBeVisible();
    await board.getByText("Site is down").click();

    const detail = page.getByTestId("board-thread");
    await expect(detail.getByText("New")).toBeVisible();

    await detail
      .getByLabel("Draft a reply")
      .fill("We're on it, restoring the site now.");
    await detail.getByRole("button", { name: "Save draft" }).click();
    await expect(detail.getByText("Drafted")).toBeVisible();
    await expect(
      detail.getByText("We're on it, restoring the site now."),
    ).toBeVisible();

    await detail.getByRole("button", { name: "Approve" }).click();
    await expect(detail.getByText("Approved", { exact: true })).toBeVisible();
    const replyBox = detail.getByLabel("Approved — send it");
    await expect(replyBox).toHaveValue("We're on it, restoring the site now.");

    await detail.getByRole("button", { name: "Send reply" }).click();
    await expect(detail.getByText("Replied")).toBeVisible();
    await expect(detail.getByText("Reply sent.")).toBeVisible();
  });

  test("is absent on client-facing MomoBot when the flag is off", async ({
    page,
  }) => {
    await mockBoard(page, { desk: false });
    await page.goto("/workspace/board");

    await page.waitForURL("**/workspace/command-center", { timeout: 15_000 });
    const sidebar = page.locator("[data-sidebar='sidebar']");
    await expect(sidebar.locator("a[href='/workspace/board']")).toHaveCount(0);
    await expect(page.getByTestId("board")).toHaveCount(0);
  });

  test("tells a fresh instance the truth: no threads yet", async ({ page }) => {
    await mockBoard(page, { threads: [] });
    await page.goto("/workspace/board");

    const board = page.getByTestId("board");
    await expect(
      board.getByText("No board threads yet", { exact: false }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(
      page.locator("[data-sidebar='sidebar'] a[href='/workspace/board']"),
    ).toBeVisible();
  });

  test("a client member can start a thread for their own client", async ({
    page,
  }) => {
    // A client contact assigned to Widget Co, a client that never appears
    // on the org's full "**/api/clients" roster in this fixture -- if the
    // picker ever fell back to that endpoint, this would show "Acme
    // Landscaping" instead and the assertion below would catch it.
    await mockBoard(page, {
      threads: [],
      myClients: [{ id: "widget-co", display_name: "Widget Co" }],
    });
    await page.goto("/workspace/board");

    const board = page.getByTestId("board");
    await expect(
      board.getByRole("heading", { level: 1, name: "Board" }),
    ).toBeVisible({ timeout: 15_000 });

    await board.getByRole("button", { name: "New thread" }).click();
    const clientSelect = board.getByLabel("Client");
    await expect(clientSelect).toBeVisible();
    // The picker is scoped to the caller's own clients (``/api/clients/mine``),
    // never the full org roster.
    await expect(clientSelect.locator("option")).toHaveText(["Widget Co"]);

    await board.getByLabel("Kind").selectOption("concern");
    await board.getByLabel("Subject").fill("Can we adjust the invoice?");
    await board.getByRole("button", { name: "Start thread" }).click();

    // Creating closes the form and selects the new thread.
    await expect(
      board.getByRole("button", { name: "Start thread" }),
    ).toHaveCount(0);
    const detail = page.getByTestId("board-thread");
    await expect(detail.getByText("Can we adjust the invoice?")).toBeVisible();
    await expect(detail.getByText("New")).toBeVisible();
  });

  test("a client member sees a thread's status but never Momo's unapproved draft", async ({
    page,
  }) => {
    await mockBoard(page, {
      threads: [
        thread("t1", {
          subject: "Site is down",
          kind: "ticket",
          status: "drafted",
        }),
      ],
      initialMessages: {
        t1: [
          {
            id: "msg-1",
            thread_id: "t1",
            author_kind: "momo",
            author_user_id: null,
            body: "We're on it, restoring the site now.",
            created_at: at(-2),
          },
        ],
      },
      hideUnapprovedDraft: true,
    });
    await page.goto("/workspace/board");

    const board = page.getByTestId("board");
    await expect(board.getByText("Site is down")).toBeVisible({
      timeout: 15_000,
    });
    await board.getByText("Site is down").click();

    const detail = page.getByTestId("board-thread");
    await expect(detail.getByText("Drafted")).toBeVisible();
    // The status is visible, but Momo's still-unapproved draft body is not.
    await expect(
      detail.getByText("We're on it, restoring the site now."),
    ).toHaveCount(0);

    await detail.getByRole("button", { name: "Approve" }).click();
    await expect(detail.getByText("Approved", { exact: true })).toBeVisible();
    // Once approved, it's the reply, not a hidden draft -- now visible (the
    // message body and the reply-editor prefill both carry the same text).
    await expect(
      detail.getByText("We're on it, restoring the site now.").first(),
    ).toBeVisible();
  });
});
