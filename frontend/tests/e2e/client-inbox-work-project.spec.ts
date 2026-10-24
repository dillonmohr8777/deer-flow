import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

for (const width of [390, 1440]) {
  test(`staff explicitly chooses and freezes a work project at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    mockLangGraphAPI(page, { scheduledTasks: [] });
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const selections = new Map<string, string | null>();
    const starts: Record<string, unknown>[] = [];
    let conflict = true;
    const row = (id: string) => ({
      id,
      client_id: "synthetic-alpha",
      subject:
        id === "one" ? "Synthetic first request" : "Synthetic second request",
      state: selections.has(id) ? "running" : "pending",
      revision: 0,
      publish_receipt: null,
      can_draft: true,
      can_review: true,
      messages: [],
      ...(selections.has(id)
        ? {
            work_chat_id: `synthetic-work-${id}`,
            work_run_id: `synthetic-run-${id}`,
          }
        : {}),
    });
    await page.route("**/api/projects?status=active", async (route) => {
      await route.fulfill({
        json: {
          projects: [
            {
              id: "linked",
              name: "Synthetic linked project",
              client_id: "synthetic-alpha",
              status: "active",
            },
            {
              id: "foreign",
              name: "Synthetic foreign project",
              client_id: "synthetic-beta",
              status: "active",
            },
            {
              id: "unlinked",
              name: "Synthetic unlinked project",
              client_id: null,
              status: "active",
            },
            {
              id: "archived",
              name: "Synthetic archived project",
              client_id: "synthetic-alpha",
              status: "archived",
            },
          ],
        },
      });
    });
    await page.route("**/api/threads/synthetic-work-*", async (route) => {
      const id = new URL(route.request().url()).pathname.split("/").at(-1)!;
      await route.fulfill({
        json: {
          thread_id: id,
          metadata: {
            deerflow_project_id:
              selections.get(id.replace("synthetic-work-", "")) ?? null,
          },
        },
      });
    });
    await page.route("**/api/client-portal/**", async (route) => {
      const url = new URL(route.request().url());
      const path = url.pathname.replace("/api/client-portal", "");
      if (path.endsWith("/work-plan"))
        return route.fulfill({
          json: {
            schema: "internal_work_plan.v1",
            revision: 0,
            plan: null,
            recorded_by_user_id: null,
            recorded_at: null,
            verification: "staff_recorded_unverified",
            source: { table: "board_portal", id: path.split("/")[2] },
          },
        });
      if (path === "/clients") {
        return route.fulfill({
          json: {
            workspace_id: "synthetic-workspace",
            clients: [{ id: "synthetic-alpha", name: "Synthetic Alpha" }],
            can_draft: true,
            can_review: true,
          },
        });
      }
      if (path === "/threads")
        return route.fulfill({
          json: { threads: [row("one"), row("two")], has_more: false },
        });
      if (path.endsWith("/context")) {
        return route.fulfill({
          json: {
            schema: "client_operating_context.v1",
            workspace_id: "synthetic-workspace",
            client: {
              id: "synthetic-alpha",
              name: "Synthetic Alpha",
              source: { updated_at: "2026-10-24T15:30:00Z" },
            },
            requests: { items: [], has_more: false },
            current_request: {
              id: url.searchParams.get("thread_id"),
              timeline: [],
              current_draft: { revision: 0 },
            },
            domains: {},
            freshness: "Stored synthetic portal evidence",
            limits: { requests: 25, messages: 40 },
          },
        });
      }
      const id = path.split("/")[2]!;
      if (path.endsWith("/work")) {
        const input = route.request().postDataJSON() as Record<string, unknown>;
        starts.push(input);
        if (conflict) {
          conflict = false;
          return route.fulfill({
            status: 409,
            json: { detail: "Synthetic project conflict. Refresh and retry." },
          });
        }
        selections.set(
          id,
          typeof input.project_id === "string" ? input.project_id : null,
        );
        return route.fulfill({
          json: {
            chat_id: `synthetic-work-${id}`,
            run_id: `synthetic-run-${id}`,
            status: "running",
            href: `/workspace/agents/momobot-max/chats/synthetic-work-${id}`,
          },
        });
      }
      return route.fulfill({ json: row(id) });
    });
    await page.goto("/workspace/inbox");
    await page.getByRole("button", { name: /Synthetic first request/ }).click();
    const picker = page.getByRole("combobox", {
      name: "Work project",
      exact: true,
    });
    const start = page.getByRole("button", {
      name: "Ask Momo to work",
      exact: true,
    });
    await expect(start).toBeDisabled();
    await expect(picker.locator("option")).toHaveText([
      "Choose a project or no project",
      "No project",
      "Synthetic linked project",
    ]);
    await picker.selectOption({ label: "Synthetic linked project" });
    await picker.scrollIntoViewIfNeeded();
    expect((await picker.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    expect((await start.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    await page.screenshot({
      path: test.info().outputPath(`work-project-picker-${width}.png`),
    });
    await start.click();
    await expect(
      page.getByRole("alert").filter({ hasText: "Synthetic project conflict" }),
    ).toBeVisible();
    await expect(start).toBeEnabled();
    expect(starts).toEqual([{ project_id: "linked" }]);
    await expect(
      page.getByText("Selection is fixed for this request.", { exact: false }),
    ).toHaveCount(0);
    await start.click();
    await page.waitForURL(
      "**/workspace/agents/momobot-max/chats/synthetic-work-one",
    );
    await page.goto("/workspace/inbox");
    await page.getByRole("button", { name: /Synthetic first request/ }).click();
    const frozen = page.getByRole("region", { name: "Work project selection" });
    await expect(
      frozen.getByText(/Work project: Synthetic linked project/),
    ).toBeVisible();
    await expect(frozen.getByRole("combobox")).toHaveCount(0);
    await frozen.screenshot({
      path: test.info().outputPath(`work-project-frozen-${width}.png`),
    });
    await page
      .getByRole("button", { name: /Synthetic second request/ })
      .click();
    await expect(picker).toHaveValue("choose");
    await expect(start).toBeDisabled();
    await picker.selectOption({ label: "No project" });
    await start.click();
    await page.waitForURL(
      "**/workspace/agents/momobot-max/chats/synthetic-work-two",
    );
    expect(starts).toEqual([
      { project_id: "linked" },
      { project_id: "linked" },
      {},
    ]);
    await page.goto("/workspace/inbox");
    await page
      .getByRole("button", { name: /Synthetic second request/ })
      .click();
    await expect(frozen.getByText(/Work project: No project/)).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    expect(errors).toEqual([]);
  });
}
