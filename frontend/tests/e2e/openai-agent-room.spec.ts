import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

// Fixture interception must stay in the page; PWA behavior has its own suite.
test.use({ serviceWorkers: "block" });

const SUMMARY = {
  id: "local-session",
  title: "Launch task",
  status: "idle",
  created_at: "2026-09-29T23:00:00Z",
  updated_at: "2026-09-29T23:00:01Z",
  last_error: null,
};
const DETAIL = {
  ...SUMMARY,
  turn: { id: "root-turn", status: "completed", output_verified: true },
  items: [
    {
      id: "answer",
      type: "message",
      turn_id: "root-turn",
      subagent_id: null,
      role: "assistant",
      text: "Three reviewed launch checks are saved in the workspace.",
      status: "completed",
    },
  ],
  artifacts: [],
  required_actions: [],
  usage: { input_tokens: null, output_tokens: null },
  operation_pending: false,
  history_truncated: false,
};

async function setup(page: Page, available = true) {
  mockLangGraphAPI(page);
  let created = false;
  const receipts: string[] = [];
  await page.route("**/api/openai-agents/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    expect(
      route.request().headers()[
        path.endsWith("/status")
          ? "x-expected-user-id"
          : "x-expected-agent-scope"
      ],
    ).toBe(path.endsWith("/status") ? "default" : "scope-one");
    let body: unknown;
    if (path.endsWith("/status"))
      body = {
        owner_scope: "scope-one",
        configured: available,
        available,
        model: "gpt-6.1-sol",
        max_concurrent_subagents: 3,
        browser_available: false,
        reason: available ? null : "missing_api_key",
      };
    else if (path.endsWith("/sessions") && route.request().method() === "GET")
      body = { data: created ? [SUMMARY] : [] };
    else if (route.request().method() === "POST") {
      receipts.push(route.request().headers()["idempotency-key"] ?? "");
      created = true;
      body = DETAIL;
    } else body = DETAIL;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
  return { receipts };
}

test("phone task returns persisted root output and survives reopening", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { receipts } = await setup(page);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/workspace/openai");
  await expect(
    page.getByRole("heading", { name: "OpenAI crew" }),
  ).toBeVisible();
  await page
    .getByLabel("Task for the crew")
    .fill("Prepare three launch checks.");
  await page.getByRole("button", { name: "Send task", exact: true }).click();
  await expect(
    page.getByText("Three reviewed launch checks are saved in the workspace."),
  ).toBeVisible();
  await expect(
    page.getByText("Turn completed · final output retrieved"),
  ).toBeVisible();
  expect(receipts).toHaveLength(1);
  expect(receipts[0]).toMatch(/^[0-9a-f-]{36}$/);
  await page.reload();
  await page.getByRole("button", { name: "Launch task idle" }).click();
  await expect(
    page.getByText("Three reviewed launch checks are saved in the workspace."),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});

test("unconfigured runtime cannot dispatch a paid request", async ({
  page,
}) => {
  const { receipts } = await setup(page, false);
  await page.goto("/workspace/openai");
  await page.getByLabel("Task for the crew").fill("A task");
  await expect(
    page.getByRole("button", { name: "Send task", exact: true }),
  ).toBeDisabled();
  expect(receipts).toHaveLength(0);
});

test("HTTP success with an unresolved admission keeps a second dispatch paused", async ({
  page,
}) => {
  await setup(page);
  const pending = {
    ...DETAIL,
    status: "unknown",
    turn: null,
    items: [],
    operation_pending: true,
  };
  await page.route("**/api/openai-agents/sessions", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(
        route.request().method() === "POST" ? pending : { data: [] },
      ),
    });
  });
  await page.route(
    "**/api/openai-agents/sessions/local-session",
    async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(pending),
      });
    },
  );
  await page.goto("/workspace/openai");
  await page.getByLabel("Task for the crew").fill("A task");
  await page.getByRole("button", { name: "Send task", exact: true }).click();
  await expect(page.getByText(/A new task stays paused/)).toBeVisible();
  await page.getByLabel("Task for the crew").fill("Another task");
  await expect(
    page.getByRole("button", { name: "Send task", exact: true }),
  ).toBeDisabled();
  await expect(page.getByText(/final output retrieved/)).toHaveCount(0);
});
