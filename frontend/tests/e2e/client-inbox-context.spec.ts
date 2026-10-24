import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

for (const width of [390, 1440]) {
  test(`staff client context and filter at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    mockLangGraphAPI(page, { scheduledTasks: [] });
    const contextReads: string[] = [];
    const row = {
      id: "synthetic-request",
      client_id: "beta",
      subject: "Synthetic Beta request",
      state: "needs_approval",
      portal_state: "needs_approval",
      status: "open",
      updated_at: "2026-10-24T10:00:00Z",
      revision: 1,
      approval_id: "synthetic-approval",
      work_chat_id: "synthetic-chat",
      work_run_id: "synthetic-run",
      publish_receipt: null,
      can_draft: true,
      can_review: true,
      draft: { body: "Synthetic draft", attachments: [] },
      messages: [],
    };
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
      expect(route.request().method()).toBe("GET");
      let data: unknown;
      if (path === "/clients") {
        data = {
          workspace_id: "synthetic-workspace",
          clients: [
            { id: "alpha", name: "Synthetic Alpha" },
            { id: "beta", name: "Synthetic Beta" },
          ],
          can_draft: true,
          can_review: true,
        };
      } else if (path === "/threads") {
        data = { threads: [], has_more: false };
      } else if (path === "/threads/synthetic-request") {
        data = row;
      } else if (
        path === "/clients/beta/context" ||
        path === "/clients/alpha/context"
      ) {
        expect(route.request().headers()["x-portal-workspace"]).toBe(
          "synthetic-workspace",
        );
        contextReads.push(url.search);
        data = {
          schema: "client_operating_context.v1",
          workspace_id: "synthetic-workspace",
          client: {
            id: path.includes("/beta/") ? "beta" : "alpha",
            name: path.includes("/beta/")
              ? "Synthetic Beta"
              : "Synthetic Alpha",
            source: { updated_at: row.updated_at },
          },
          requests: {
            items: path.includes("/beta/") ? [row] : [],
            has_more: true,
          },
          current_request: url.searchParams.has("thread_id")
            ? {
                ...row,
                timeline: [
                  {
                    id: "synthetic-message",
                    author_kind: "client",
                    visibility: "public",
                    created_at: row.updated_at,
                    body: '<img src=x onerror="alert(1)"> Supplied request text',
                    body_truncated: true,
                    attachments: [],
                  },
                ],
                timeline_truncated: true,
                current_draft: { revision: 1 },
              }
            : null,
          domains: {
            client_identity: {
              status: "available",
              scope: "Stored roster identity only.",
            },
            request_history: {
              status: "available",
              scope: "Portal history in this workspace only.",
            },
            goals: {
              status: "unavailable",
              reason: "No dedicated source is included in this projection.",
            },
            crm: {
              status: "unavailable",
              reason: "No dedicated source is included in this projection.",
            },
            campaign_performance: {
              status: "unavailable",
              reason: "No dedicated source is included in this projection.",
            },
            meetings: {
              status: "unavailable",
              reason: "No dedicated source is included in this projection.",
            },
            delivery_priorities: {
              status: "unavailable",
              reason: "No dedicated source is included in this projection.",
            },
          },
          freshness:
            "Source timestamps describe stored records; provider freshness is unavailable.",
          limits: { requests: 25, messages: 40 },
        };
      } else {
        throw new Error(`Unexpected portal path: ${path}`);
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(data),
      });
    });
    await page.goto("/workspace/inbox");
    await expect(
      page.getByRole("heading", { name: "Client inbox", exact: true }),
    ).toBeVisible();
    await page
      .getByRole("combobox", { name: "Filter by client" })
      .selectOption("beta");
    const panel = page.getByRole("region", { name: "Client context" });
    await expect(
      panel.getByRole("heading", { name: "Synthetic Beta", exact: true }),
    ).toBeVisible();
    await expect(panel.getByText("Unavailable", { exact: true })).toHaveCount(
      5,
    );
    await page
      .getByRole("complementary", { name: "Inbox conversations" })
      .getByRole("button", { name: /Synthetic Beta request/ })
      .click();
    await expect(
      panel.getByRole("link", { name: "Run history" }),
    ).toHaveAttribute("href", "/workspace/command-center");
    await expect(
      panel.getByRole("link", { name: "Approvals", exact: true }),
    ).toHaveAttribute("href", "/workspace/approvals");
    await expect(
      panel.getByRole("link", { name: "Board", exact: true }),
    ).toHaveAttribute("href", "/workspace/board");
    await panel.getByText("Request timeline", { exact: true }).click();
    await expect(panel.getByText(/Supplied request text/)).toBeVisible();
    await expect(panel.locator("img")).toHaveCount(0);
    expect(contextReads).toContain("?thread_id=synthetic-request");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    expect(errors).toEqual([]);
    await page
      .getByRole("heading", { name: "Client inbox", exact: true })
      .scrollIntoViewIfNeeded();
    await page.screenshot({
      path: test.info().outputPath(`inbox-context-${width}.png`),
      fullPage: true,
    });
    await page
      .getByRole("combobox", { name: "Filter by client" })
      .selectOption("alpha");
    await expect(
      page.getByRole("textbox", { name: "Internal reply draft", exact: true }),
    ).toHaveCount(0);
    await expect(page.getByText(/Supplied request text/)).toHaveCount(0);
  });
}
