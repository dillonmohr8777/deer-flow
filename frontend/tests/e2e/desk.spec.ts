import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const at = (hours: number) =>
  new Date(Date.now() + hours * 3_600_000).toISOString();

const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const TASK = {
  thread_id: null,
  schedule_type: "cron" as const,
  timezone: "America/New_York",
  status: "enabled" as const,
  last_run_id: null,
  last_error: null,
  run_count: 1,
  created_at: at(-72),
  updated_at: at(-1),
};

function template(id: string, name: string) {
  return {
    id,
    version: "1",
    name,
    description: "",
    model: "openrouter-opus-5.5",
    skills: [],
    tool_groups: [],
    mcp_plugins: [],
    schedule: { cron: "0 9 * * 1", timezone: "America/New_York" },
    acceptance_criteria: [],
  };
}

type BoardThreadFixture = {
  id: string;
  status: string;
  urgency: string | null;
};

async function mockWorkspace(
  page: Page,
  {
    desk,
    fresh = false,
    boardThreads = [],
    lastError = null,
  }: {
    desk: boolean;
    fresh?: boolean;
    boardThreads?: BoardThreadFixture[];
    lastError?: string | null;
  },
) {
  mockLangGraphAPI(page, {
    scheduledTasks: fresh
      ? []
      : [
          {
            ...TASK,
            id: "task-cos",
            assistant_id: "chief-of-staff",
            title: "Chief of Staff",
            prompt: "Morning brief",
            schedule_spec: { cron: "30 8 * * 1-5" },
            next_run_at: at(16),
            last_run_at: at(-3),
            last_thread_id: "thread-cos",
            last_error: lastError,
          },
          {
            ...TASK,
            id: "task-acme",
            assistant_id: "acme-client-reporter",
            title: "Weekly report for Acme",
            prompt: "Weekly report",
            schedule_spec: { cron: "0 9 * * 5" },
            next_run_at: at(40),
            last_run_at: at(-150),
            last_thread_id: "thread-acme",
          },
        ],
  });
  // Registered after mockLangGraphAPI, so these win over its defaults.
  await page.route("**/api/features", (route) =>
    route.fulfill(
      json({ agents_api: { enabled: true }, desk: { enabled: desk } }),
    ),
  );
  await page.route("**/api/fleet/templates", (route) =>
    route.fulfill(
      json({
        templates: fresh
          ? []
          : [
              template("chief-of-staff", "Chief of Staff"),
              template("client-reporter", "Client Reporter"),
            ],
      }),
    ),
  );
  await page.route("**/api/clients", (route) =>
    route.fulfill(
      json({
        clients: fresh
          ? []
          : [
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
  await page.route("**/api/clients/*/agents", (route) =>
    route.fulfill(
      json({
        agents: [
          {
            client_id: "acme",
            template_id: "client-reporter",
            template_version: "1",
            agent_name: "acme-client-reporter",
            display_name: null,
            description: null,
            scheduled_task_id: "task-acme",
            created_at: at(-200),
            updated_at: at(-200),
          },
        ],
      }),
    ),
  );
  await page.route("**/api/console/usage*", (route) =>
    route.fulfill(
      json({
        days: [],
        by_model: fresh
          ? {}
          : {
              "openrouter-opus-5.5": {
                tokens: 120_000,
                runs: 3,
                cost: 1.2,
                input_tokens: 100_000,
                cache_read_tokens: 0,
              },
            },
        total_tokens: fresh ? 0 : 120_000,
        total_runs: fresh ? 0 : 3,
        total_cost: fresh ? null : 1.2,
        currency: fresh ? null : "USD",
      }),
    ),
  );
  await page.route("**/api/board/threads*", (route) =>
    route.fulfill(
      json({
        threads: boardThreads.map((thread) => ({
          id: thread.id,
          client_id: "acme",
          kind: "ticket",
          status: thread.status,
          subject: "Site is down",
          urgency: thread.urgency,
          summary: null,
          created_by_user_id: "client-1",
          created_at: at(-200),
          updated_at: at(-200),
        })),
      }),
    ),
  );
}

test.describe("Desk, the owner-only home", () => {
  test("shows on the private instance when the flag is on", async ({
    page,
  }) => {
    await mockWorkspace(page, { desk: true });
    await page.goto("/workspace/desk");

    const desk = page.getByTestId("desk");
    await expect(
      desk.getByRole("heading", { level: 1, name: "Desk" }),
    ).toBeVisible({ timeout: 15_000 });
    for (const name of ["Today", "Clients", "Agents", "Model lanes"]) {
      await expect(desk.getByRole("heading", { level: 2, name })).toBeVisible();
    }
    // Chief of Staff finished 3 hours ago: a draft waiting on the owner.
    await expect(desk.getByText("Ready for review")).toBeVisible();
    await expect(desk.getByText("Nothing waiting")).toBeVisible();
    await expect(desk.getByRole("group", { name: "Command" })).toContainText(
      "Chief of Staff",
    );
    await expect(desk.getByText("Acme Landscaping")).toBeVisible();
    await expect(desk.getByText("Weekly report for Acme")).toBeVisible();
    await expect(
      page.locator("[data-sidebar='sidebar'] a[href='/workspace/desk']"),
    ).toBeVisible();
  });

  test("is absent on client-facing MomoBot when the flag is off", async ({
    page,
  }) => {
    await mockWorkspace(page, { desk: false });
    await page.goto("/workspace/desk");

    await page.waitForURL("**/workspace/command-center", { timeout: 15_000 });
    const sidebar = page.locator("[data-sidebar='sidebar']");
    await expect(
      sidebar.getByRole("link", { name: "Command Center", exact: true }),
    ).toBeVisible();
    await expect(sidebar.locator("a[href='/workspace/desk']")).toHaveCount(0);
    await expect(page.getByTestId("desk")).toHaveCount(0);
  });

  test("tells a fresh instance the truth: nothing has run yet", async ({
    page,
  }) => {
    await mockWorkspace(page, { desk: true, fresh: true });
    await page.goto("/workspace/desk");

    const desk = page.getByTestId("desk");
    await expect(
      desk.getByText("No scheduled agent has run on this instance yet", {
        exact: false,
      }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(desk.getByText("No clients yet")).toBeVisible();
    await expect(
      desk.getByText("No agents on this instance yet"),
    ).toBeVisible();
    await expect(desk.getByText("No model calls yet")).toBeVisible();
  });

  test.describe("on a phone", () => {
    test.use({
      viewport: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
      userAgent:
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    });

    test("a Today slip puts its time under the title, and a failure folds its corner", async ({
      page,
    }) => {
      await mockWorkspace(page, {
        desk: true,
        lastError: "Google Ads token expired, reconnect the account",
      });
      await page.goto("/workspace/desk");

      const today = page.locator("section[aria-labelledby='desk-today'] li");
      await expect(today).toHaveCount(1, { timeout: 15_000 });
      const slip = today.first();
      const title = slip.getByText("Chief of Staff", { exact: true });
      const when = slip.getByText(/\d:\d\d [AP]M$/);
      const reason = slip.getByText("Google Ads token expired", {
        exact: false,
      });
      const link = slip.getByRole("link", { name: /Open receipt/ });

      const [t, w, r, l] = await Promise.all(
        [title, when, reason, link].map((el) => el.boundingBox()),
      );
      // Title, then when, then the reason, then the foot line.
      expect(w!.y).toBeGreaterThanOrEqual(t!.y + t!.height - 1);
      expect(r!.y).toBeGreaterThanOrEqual(w!.y + w!.height - 1);
      expect(l!.y).toBeGreaterThanOrEqual(r!.y + r!.height - 1);
      // The reason is a real failure, so it reads in danger.
      await expect(reason).toHaveCSS("color", "rgb(154, 43, 60)");
      // The torn corner: a clipped slip and a kraft flap in the corner.
      await expect(slip).toHaveAttribute("data-failed", "true");
      expect(
        await slip.evaluate((el) => getComputedStyle(el).clipPath),
      ).toContain("polygon");
      const flap = slip.locator("[aria-hidden='true']").first();
      await expect(flap).toBeVisible();
      await expect(flap).toHaveCSS("background-color", "rgb(216, 195, 160)");
    });

    test("an agent row leads with its Momo and folds into three lines", async ({
      page,
    }) => {
      await mockWorkspace(page, { desk: true });
      await page.goto("/workspace/desk");

      const rows = page.locator("section[aria-labelledby='desk-agents'] li");
      await expect(rows).toHaveCount(2, { timeout: 15_000 });
      // The client reporter wears the canon client-success Momo.
      await expect(
        rows.nth(1).locator("img[src='/momentum/momos/client-success.svg']"),
      ).toBeVisible();

      const row = rows.first();
      const face = row.locator("[data-size]");
      const name = row.getByText("Chief of Staff", { exact: true });
      const model = name.locator("xpath=following-sibling::*[1]");
      const next = row.getByText(/^Next /);
      const receipt = row.getByRole("link", { name: /Open receipt/ });
      const [f, n, m, x, r, box] = await Promise.all(
        [face, name, model, next, receipt, row].map((el) => el.boundingBox()),
      );
      // The face holds a left column; the words sit right of it.
      expect(n!.x).toBeGreaterThanOrEqual(f!.x + f!.width);
      // Model and next run share the second line; the receipt is below it.
      expect(Math.abs(m!.y - x!.y)).toBeLessThan(4);
      expect(m!.y).toBeGreaterThanOrEqual(n!.y + n!.height - 1);
      expect(r!.y + r!.height / 2).toBeGreaterThan(m!.y + m!.height);
      // Three lines, not the four stacked lines it was (116px).
      expect(box!.height).toBeLessThanOrEqual(96);
      // The receipt link is a 44px target without growing the row.
      expect(r!.height).toBeGreaterThanOrEqual(44);
    });

    test("a result that did not fail keeps its corner", async ({ page }) => {
      await mockWorkspace(page, { desk: true });
      await page.goto("/workspace/desk");

      const slip = page
        .locator("section[aria-labelledby='desk-today'] li")
        .first();
      await expect(slip.getByText("Ready for review")).toBeVisible({
        timeout: 15_000,
      });
      expect(await slip.evaluate((el) => getComputedStyle(el).clipPath)).toBe(
        "none",
      );
    });
  });

  test("shows a count of threads waiting on the owner's approval, on the Desk and in the sidebar", async ({
    page,
  }) => {
    await mockWorkspace(page, {
      desk: true,
      boardThreads: [
        { id: "t1", status: "drafted", urgency: "normal" },
        { id: "t2", status: "drafted", urgency: "low" },
      ],
    });
    await page.goto("/workspace/desk");

    const desk = page.getByTestId("desk");
    await expect(desk.getByText("2 waiting on you")).toBeVisible({
      timeout: 15_000,
    });
    await expect(desk.getByText("After hours")).toHaveCount(0);

    const boardItem = page.locator(
      "[data-sidebar='sidebar'] [data-sidebar='menu-item']:has(a[href='/workspace/board'])",
    );
    await expect(boardItem.locator("a[href='/workspace/board']")).toBeVisible();
    await expect(boardItem.locator("[data-sidebar='menu-badge']")).toHaveText(
      "2",
    );
  });

  test("flags an urgent waiting thread as after hours outside 8am-8pm ET", async ({
    page,
  }) => {
    // 2am ET: well outside the 8am-8pm window, no DST ambiguity.
    await page.clock.install({
      time: new Date("2026-09-24T06:00:00.000Z"), // 02:00 America/New_York
    });
    await mockWorkspace(page, {
      desk: true,
      boardThreads: [{ id: "t1", status: "drafted", urgency: "urgent" }],
    });
    await page.goto("/workspace/desk");

    const desk = page.getByTestId("desk");
    await expect(desk.getByText("1 waiting on you")).toBeVisible({
      timeout: 15_000,
    });
    await expect(desk.getByText("After hours")).toBeVisible();
  });
});
