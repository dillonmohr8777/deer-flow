import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const at = (hours: number) =>
  new Date(Date.now() + hours * 3_600_000).toISOString();

const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

type Draft = {
  thread_id: string;
  client_id: string | null;
  kind: string;
  subject: string;
  status: "drafted" | "approved";
  draft_body: string | null;
  updated_at: string;
};

type SeatClaim = {
  seat_id: string;
  seat: string;
  agent_name: string;
  claimed_by_user_id: string | null;
  created_at: string;
};

type SeatRow = {
  seat_id: string;
  seat: string;
  agent_name: string;
  kpi: string;
  status: "claimed" | "ratified" | "reopened";
  weekly_token_budget: number;
  burn_this_week: number;
  paused: boolean;
};

type FeedMessage = {
  id: string;
  author_user_id: string;
  author_display_name: string;
  body: string;
  created_at: string;
};

async function mockCeoDesk(
  page: Page,
  {
    ceo = true,
    momentumInternal = true,
    drafts = [],
    claims = [],
    seats = [],
    digest = null,
    execMessages = [],
    fleetExists = false,
    fleetMessages = [],
  }: {
    ceo?: boolean;
    /** f189: the live #exec/#fleet feeds are gated on the agency workspace. */
    momentumInternal?: boolean;
    drafts?: Draft[];
    claims?: SeatClaim[];
    seats?: SeatRow[];
    digest?: {
      digest_text: string;
      shipped_count: number;
      stuck_count: number;
      needs_my_yes_drafts: number;
      needs_my_yes_ratifications: number;
      created_at: string;
    } | null;
    execMessages?: FeedMessage[];
    fleetExists?: boolean;
    fleetMessages?: FeedMessage[];
  } = {},
) {
  mockLangGraphAPI(page, { scheduledTasks: [] });

  const draftState = new Map(drafts.map((d) => [d.thread_id, d]));
  const claimState = new Map(claims.map((c) => [c.seat_id, c]));
  const seatState = new Map(seats.map((s) => [s.seat_id, s]));
  const feedState: Record<
    "exec" | "fleet",
    { exists: boolean; messages: FeedMessage[] }
  > = {
    exec: { exists: true, messages: [...execMessages] },
    fleet: { exists: fleetExists, messages: [...fleetMessages] },
  };

  await page.route("**/api/features", (route) =>
    route.fulfill(
      json({
        agents_api: { enabled: true },
        desk: { enabled: false },
        ceo: { enabled: ceo },
        momentum_internal: { enabled: momentumInternal },
      }),
    ),
  );

  await page.route("**/api/ceo/needs-my-yes", (route) =>
    route.fulfill(
      json({
        board_drafts: [...draftState.values()],
        seat_ratifications: [...claimState.values()],
      }),
    ),
  );

  await page.route("**/api/ceo/seats", (route) =>
    route.fulfill(json({ seats: [...seatState.values()] })),
  );

  await page.route("**/api/ceo/digest", (route) =>
    route.fulfill(json({ digest })),
  );

  // FeedsSection's author lookup is best-effort; a mocked empty directory
  // keeps the feed test deterministic without needing momentum_internal's
  // own mock setup.
  await page.route("**/api/team/members", (route) =>
    route.fulfill(json({ members: [] })),
  );

  await page.route(/\/api\/ceo\/seats\/([^/]+)\/ratify$/, async (route) => {
    const id = /seats\/([^/]+)\/ratify/.exec(route.request().url())![1]!;
    claimState.delete(id);
    const seat = seatState.get(id);
    if (seat) seatState.set(id, { ...seat, status: "ratified" });
    await route.fulfill(
      json({
        seat_id: id,
        seat: seat?.seat ?? id,
        agent_name: seat?.agent_name ?? "",
        status: "ratified",
      }),
    );
  });

  await page.route(/\/api\/ceo\/seats\/([^/]+)\/reopen$/, async (route) => {
    const id = /seats\/([^/]+)\/reopen/.exec(route.request().url())![1]!;
    claimState.delete(id);
    const seat = seatState.get(id);
    if (seat) seatState.set(id, { ...seat, status: "reopened" });
    await route.fulfill(
      json({
        seat_id: id,
        seat: seat?.seat ?? id,
        agent_name: seat?.agent_name ?? "",
        status: "reopened",
      }),
    );
  });

  await page.route(
    /\/api\/board\/threads\/([^/]+)\/approve$/,
    async (route) => {
      const id = /threads\/([^/]+)\/approve/.exec(route.request().url())![1]!;
      const draft = draftState.get(id);
      if (draft) draftState.set(id, { ...draft, status: "approved" });
      await route.fulfill(
        json({
          id,
          client_id: draft?.client_id ?? null,
          kind: draft?.kind ?? "ticket",
          status: "approved",
          subject: draft?.subject ?? "",
          created_by_user_id: null,
          created_at: at(-4),
          updated_at: at(0),
        }),
      );
    },
  );

  await page.route(
    /\/api\/ceo\/channels\/([^/]+)\/messages$/,
    async (route) => {
      const slug = /channels\/([^/]+)\/messages/.exec(
        route.request().url(),
      )![1]! as "exec" | "fleet";
      const state = feedState[slug];
      if (route.request().method() === "GET") {
        await route.fulfill(
          json({
            channel: slug,
            exists: state.exists,
            messages: state.messages,
          }),
        );
        return;
      }
      if (!state.exists) {
        await route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({
            detail: `No #${slug} channel in this organization yet.`,
          }),
        });
        return;
      }
      const body = JSON.parse(route.request().postData() ?? "{}") as {
        body: string;
      };
      const message: FeedMessage = {
        id: `${slug}-${state.messages.length + 1}`,
        author_user_id: "user-1",
        author_display_name: "You",
        body: body.body,
        created_at: at(0),
      };
      state.messages.push(message);
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(message),
      });
    },
  );

  await page.route(/\/api\/board\/threads\/([^/]+)\/reply$/, async (route) => {
    const id = /threads\/([^/]+)\/reply/.exec(route.request().url())![1]!;
    draftState.delete(id);
    const claim = draftState.get(id);
    await route.fulfill(
      json({
        id,
        client_id: claim?.client_id ?? null,
        kind: claim?.kind ?? "ticket",
        status: "replied",
        subject: claim?.subject ?? "",
        created_by_user_id: null,
        created_at: at(-4),
        updated_at: at(0),
      }),
    );
  });
}

function draft(id: string, patch: Partial<Draft> = {}): Draft {
  return {
    thread_id: id,
    client_id: "acme",
    kind: "ticket",
    subject: `Thread ${id}`,
    status: "drafted",
    draft_body: "We're on it, restoring the site now.",
    updated_at: at(-2),
    ...patch,
  };
}

function claim(id: string, patch: Partial<SeatClaim> = {}): SeatClaim {
  return {
    seat_id: id,
    seat: "CFO",
    agent_name: "Ledger",
    claimed_by_user_id: "user-2",
    created_at: at(-3),
    ...patch,
  };
}

function seat(id: string, patch: Partial<SeatRow> = {}): SeatRow {
  return {
    seat_id: id,
    seat: "CFO",
    agent_name: "Ledger",
    kpi: "Close the books by the 3rd",
    status: "ratified",
    weekly_token_budget: 100_000,
    burn_this_week: 40_000,
    paused: false,
    ...patch,
  };
}

test.describe("CEO Desk", () => {
  test("shows the digest, approves a draft and ratifies a seat", async ({
    page,
  }) => {
    await mockCeoDesk(page, {
      drafts: [draft("t1", { subject: "Site is down" })],
      claims: [claim("s1")],
      seats: [seat("s1", { status: "claimed" })],
      digest: {
        digest_text: "3 threads shipped, 1 stuck, 2 need your yes.",
        shipped_count: 3,
        stuck_count: 1,
        needs_my_yes_drafts: 1,
        needs_my_yes_ratifications: 1,
        created_at: at(-1),
      },
    });
    await page.goto("/workspace/ceo");

    const desk = page.getByTestId("ceo-desk");
    await expect(
      desk.getByRole("heading", { level: 1, name: "CEO Desk" }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(
      desk.getByText("3 threads shipped, 1 stuck, 2 need your yes."),
    ).toBeVisible();
    await expect(desk.getByText("Site is down")).toBeVisible();
    await expect(
      desk.getByText("We're on it, restoring the site now."),
    ).toBeVisible();

    await desk.getByRole("button", { name: "Approve Site is down" }).click();
    await expect(
      desk.getByRole("button", { name: "Send reply to Site is down" }),
    ).toBeVisible();

    await expect(desk.getByText("CFO", { exact: true }).first()).toBeVisible();
    await desk.getByRole("button", { name: "Ratify CFO for Ledger" }).click();
    await expect(
      desk.getByRole("button", { name: "Ratify CFO for Ledger" }),
    ).toHaveCount(0);

    await expect(
      page.locator("[data-sidebar='sidebar'] a[href='/workspace/ceo']"),
    ).toBeVisible();
  });

  test("is absent for anyone who isn't an owner or admin", async ({ page }) => {
    await mockCeoDesk(page, { ceo: false });
    await page.goto("/workspace/ceo");

    await page.waitForURL("**/workspace/command-center", { timeout: 15_000 });
    const sidebar = page.locator("[data-sidebar='sidebar']");
    await expect(sidebar.locator("a[href='/workspace/ceo']")).toHaveCount(0);
    await expect(page.getByTestId("ceo-desk")).toHaveCount(0);
  });

  test("tells a fresh instance the truth: nothing waiting, no seats, no digest yet", async ({
    page,
  }) => {
    await mockCeoDesk(page);
    await page.goto("/workspace/ceo");

    const desk = page.getByTestId("ceo-desk");
    await expect(desk.getByText("No digest yet")).toBeVisible({
      timeout: 15_000,
    });
    await expect(desk.getByText("Nothing waiting on you")).toBeVisible();
    await expect(desk.getByText("No seats yet")).toBeVisible();
  });

  test("reads the live #exec feed and replies; #fleet shows a not-yet-created state", async ({
    page,
  }) => {
    await mockCeoDesk(page, {
      execMessages: [
        {
          id: "exec-1",
          author_user_id: "user-2",
          author_display_name: "Momentum",
          body: "[cmo-agent] pipeline review posted to the board",
          created_at: at(-1),
        },
      ],
      fleetExists: false,
    });
    await page.goto("/workspace/ceo");

    const execPanel = page.getByTestId("ceo-feed-exec");
    await expect(
      execPanel.getByText("pipeline review posted to the board"),
    ).toBeVisible({ timeout: 15_000 });

    const fleetPanel = page.getByTestId("ceo-feed-fleet");
    await expect(fleetPanel.getByText(/No #fleet channel yet/)).toBeVisible();

    await execPanel.getByLabel("Message #exec").fill("Great work, team.");
    await execPanel.getByRole("button", { name: "Send" }).click();
    await expect(execPanel.getByText("Great work, team.")).toBeVisible();
  });

  test("hides the live feeds entirely off the agency workspace (f189)", async ({
    page,
  }) => {
    await mockCeoDesk(page, { momentumInternal: false });
    await page.goto("/workspace/ceo");

    const desk = page.getByTestId("ceo-desk");
    await expect(desk.getByText("No digest yet")).toBeVisible({
      timeout: 15_000,
    });
    await expect(desk.getByText("Live feeds")).toHaveCount(0);
    await expect(page.getByTestId("ceo-feed-exec")).toHaveCount(0);
  });
});

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

test.describe("CEO Desk layout", () => {
  for (const width of [390, 768, 1440]) {
    test(`no horizontal overflow at ${width}px`, async ({ page }) => {
      await mockCeoDesk(page, {
        drafts: [
          draft("t1", { subject: "Site is down" }),
          draft("t2", {
            subject: "Ad spend is way up this week and I am worried",
            status: "approved",
          }),
        ],
        claims: [claim("s1")],
        seats: [
          seat("s1", { status: "claimed" }),
          seat("s2", { seat: "COO", agent_name: "Foreman", paused: true }),
        ],
        digest: {
          digest_text: "3 threads shipped, 1 stuck, 2 need your yes.",
          shipped_count: 3,
          stuck_count: 1,
          needs_my_yes_drafts: 2,
          needs_my_yes_ratifications: 1,
          created_at: at(-1),
        },
        execMessages: [
          {
            id: "exec-1",
            author_user_id: "user-2",
            author_display_name: "Momentum",
            body: "[cmo-agent] pipeline review posted to the board, a fairly long line of status text to stress the layout",
            created_at: at(-1),
          },
        ],
        fleetExists: true,
        fleetMessages: [
          {
            id: "fleet-1",
            author_user_id: "user-3",
            author_display_name: "Momentum",
            body: "[fleet-builder] shipped the migration script",
            created_at: at(-1),
          },
        ],
      });
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/workspace/ceo");

      await expect(
        page.getByRole("heading", { level: 1, name: "CEO Desk" }),
      ).toBeVisible({ timeout: 15_000 });
      await expectNoHorizontalOverflow(page);
    });
  }
});
