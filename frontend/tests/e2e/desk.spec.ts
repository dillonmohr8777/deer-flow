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

async function mockWorkspace(
  page: Page,
  { desk, fresh = false }: { desk: boolean; fresh?: boolean },
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
    await expect(desk.getByText("Not wired")).toBeVisible();
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
});
