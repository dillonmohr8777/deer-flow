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
  { desk = true, threads = [] }: { desk?: boolean; threads?: Thread[] } = {},
) {
  mockLangGraphAPI(page, { scheduledTasks: [] });

  const state = new Map<string, Thread>(threads.map((t) => [t.id, t]));
  const messages = new Map<string, Message[]>();
  let nextMessageId = 1;

  await page.route("**/api/features", (route) =>
    route.fulfill(
      json({ agents_api: { enabled: true }, desk: { enabled: desk } }),
    ),
  );
  await page.route("**/api/clients", (route) =>
    route.fulfill(
      json({
        clients: [
          {
            id: "acme",
            display_name: "Acme Landscaping",
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
          },
        ],
      }),
    ),
  );

  await page.route("**/api/board/threads", async (route: Route) => {
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
      await route.fulfill(json({ messages: messages.get(id) ?? [] }));
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

/** WCAG contrast of an element's text against the first opaque background behind it. */
async function textContrast(page: Page, selector: string): Promise<number> {
  return page
    .locator(selector)
    .first()
    .evaluate((el) => {
      const parse = (value: string) => {
        const m = /rgba?\(([^)]+)\)/.exec(value);
        const [r = 0, g = 0, b = 0, a = 1] = (m?.[1] ?? "0,0,0,0")
          .split(/[ ,/]+/)
          .filter(Boolean)
          .map(Number);
        return { r, g, b, a: m ? a : 0 };
      };
      const lum = ({ r, g, b }: { r: number; g: number; b: number }) => {
        const c = [r, g, b].map((v) => {
          const x = v / 255;
          return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
        });
        return 0.2126 * c[0]! + 0.7152 * c[1]! + 0.0722 * c[2]!;
      };
      const fg = parse(getComputedStyle(el).color);
      let node: Element | null = el;
      let bg = { r: 255, g: 255, b: 255, a: 1 };
      while (node) {
        const candidate = parse(getComputedStyle(node).backgroundColor);
        if (candidate.a >= 1) {
          bg = candidate;
          break;
        }
        node = node.parentElement;
      }
      const [hi, lo] = [lum(fg), lum(bg)].sort((a, b) => b - a) as [
        number,
        number,
      ];
      return (hi + 0.05) / (lo + 0.05);
    });
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
    const replyBox = detail.getByLabel("Approved reply");
    await expect(replyBox).toHaveValue("We're on it, restoring the site now.");

    await detail.getByRole("button", { name: "Send reply" }).click();
    await expect(detail.getByText("Replied")).toBeVisible();
    await expect(detail.getByText("Reply sent.")).toBeVisible();

    // The sent reply is a letter from Momentum, and the draft it came from
    // is not repeated beside it.
    const letters = detail.locator("li[data-author]");
    await expect(letters).toHaveCount(1);
    await expect(letters.first()).toHaveAttribute("data-author", "owner");
    await expect(letters.first()).toContainText("Momentum");
    for (const part of ["p:last-child", "p:first-child time"]) {
      expect(
        await textContrast(page, `[data-author="owner"] ${part}`),
      ).toBeGreaterThanOrEqual(4.5);
    }
  });

  test("puts Momo's draft on its own sheet, readable in paper", async ({
    page,
  }) => {
    await mockBoard(page, {
      threads: [thread("t1", { subject: "Site is down", kind: "ticket" })],
    });
    await page.goto("/workspace/board");
    const board = page.getByTestId("board");
    await board.getByText("Site is down").click({ timeout: 15_000 });
    const detail = page.getByTestId("board-thread");
    await detail.getByLabel("Draft a reply").fill("Restoring it now.");
    await detail.getByRole("button", { name: "Save draft" }).click();

    const sheet = page.getByTestId("board-draft-sheet");
    await expect(
      sheet.getByRole("heading", { name: "Momo's draft" }),
    ).toBeVisible();
    await expect(sheet.getByText("Restoring it now.")).toBeVisible();
    // Shown once: on the sheet, not also as a letter.
    await expect(detail.locator("li[data-author='momo']")).toHaveCount(0);
    for (const selector of [
      "[data-testid='board-draft-sheet'] h3",
      "[data-testid='board-draft-sheet'] h3 + p",
      "[data-testid='board-draft-sheet'] > p",
    ]) {
      expect(await textContrast(page, selector)).toBeGreaterThanOrEqual(4.5);
    }
  });

  test("shows one pane at a time on a phone", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockBoard(page, {
      threads: [
        thread("t1", { subject: "Site is down" }),
        thread("t2", { subject: "Invoice question", kind: "dm" }),
      ],
    });
    await page.goto("/workspace/board");
    const board = page.getByTestId("board");
    const slip = board.getByRole("button", { name: /Invoice question/ });
    await slip.click({ timeout: 15_000 });

    const detail = page.getByTestId("board-thread");
    await expect(
      detail.getByRole("heading", { level: 2, name: "Invoice question" }),
    ).toBeFocused();
    await expect(board.getByRole("region", { name: "Threads" })).toBeHidden();

    await detail.getByRole("button", { name: "All threads" }).click();
    await expect(board.getByRole("region", { name: "Threads" })).toBeVisible();
    await expect(slip).toBeFocused();
    await expect(page.getByTestId("board-thread")).toHaveCount(0);
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
});
