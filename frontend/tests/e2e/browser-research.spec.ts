import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

// A claimed worker can bypass page.route() and reach the paid backend.
test.use({ serviceWorkers: "block" });

const SUMMARY = {
  id: "owned-capture",
  title: "Official docs",
  status: "completed",
  created_at: "2026-09-29T23:00:00Z",
  updated_at: "2026-09-29T23:00:01Z",
  last_error: null,
};
const DETAIL = {
  ...SUMMARY,
  urls: ["https://developers.openai.com/api/docs/"],
  pages: [
    {
      index: 0,
      url: "https://developers.openai.com/api/docs/",
      final_url: "https://developers.openai.com/api/docs/",
      title: "OpenAI documentation",
      text: "<script>window.__capturedScriptRan=true</script> Captured official documentation.",
      content_type: "text/html",
      screenshot_url:
        "/api/browserbase/research/owned-capture/pages/0/screenshot",
      source_mode: "public_read_only_snapshot",
    },
  ],
  session_id: "provider-session",
  replay_url: null,
  session_closed: true,
  usage: { browser_minutes: null, elapsed_seconds: 1, cost_usd: null },
};

async function setup(page: Page, available = true) {
  mockLangGraphAPI(page);
  let created = false;
  const receipts: string[] = [];
  await page.route("**/api/browserbase/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    expect(
      request.headers()[
        path.endsWith("/status")
          ? "x-expected-user-id"
          : "x-expected-browserbase-scope"
      ],
    ).toBe(path.endsWith("/status") ? "default" : "scope-one");
    let body: unknown;
    if (path.endsWith("/status"))
      body = {
        owner_scope: "scope-one",
        configured: available,
        available,
        reason: available ? null : "unverified_quota",
        browser_minutes: null,
        monthly_minute_limit: null,
        remaining_minutes: null,
        mode: "public_read_only_snapshot",
        limits: {
          max_pages: 3,
          session_timeout_seconds: 180,
          max_sessions_per_owner: 1,
        },
      };
    else if (path.endsWith("/screenshot")) {
      await route.fulfill({
        contentType: "image/png",
        body: Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGP4/x8AAwAB//wl3FEAAAAASUVORK5CYII=",
          "base64",
        ),
      });
      return;
    } else if (path.endsWith("/research") && request.method() === "GET")
      body = { data: created ? [SUMMARY] : [] };
    else if (request.method() === "POST") {
      receipts.push(request.headers()["idempotency-key"] ?? "");
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

test("persisted public capture reopens on phone and downloads actual evidence", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { receipts } = await setup(page);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/workspace/browser-research");
  await expect(
    page.getByRole("heading", { name: "Browser research", exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Public HTTPS URLs, one per line")
    .fill("https://developers.openai.com/api/docs/");
  await page
    .getByRole("button", { name: "Capture pages", exact: true })
    .click();
  await expect(
    page.getByText("Capture completed · captured evidence retrieved"),
  ).toBeVisible();
  expect(receipts).toHaveLength(1);
  expect(receipts[0]).toMatch(/^[0-9a-f-]{36}$/);
  await page.getByText("Read captured text", { exact: true }).click();
  await expect(
    page.getByText(DETAIL.pages[0]!.text, { exact: true }),
  ).toBeVisible();
  expect(await page.evaluate(() => "__capturedScriptRan" in window)).toBe(
    false,
  );
  await page
    .getByRole("button", { name: "View screenshot", exact: true })
    .click();
  await expect(
    page.getByRole("img", { name: /Browserbase rendering/ }),
  ).toBeVisible();
  await expect
    .poll(() =>
      page
        .getByRole("img", { name: /Browserbase rendering/ })
        .evaluate((image) => (image as HTMLImageElement).naturalWidth),
    )
    .toBe(1);
  const downloaded = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download evidence", exact: true })
    .click();
  const download = await downloaded;
  expect(download.suggestedFilename()).toBe(
    "browser-research-owned-capture.json",
  );
  const savedPath = await download.path();
  expect(savedPath).not.toBeNull();
  const saved = JSON.parse(readFileSync(savedPath, "utf8")) as typeof DETAIL;
  expect(saved.pages[0]?.text).toBe(DETAIL.pages[0]!.text);
  expect(saved.usage.cost_usd).toBeNull();
  await expect(
    page.getByText(/Confirm the saved file in Downloads/),
  ).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Official docs completed" }).click();
  await expect(
    page.getByText("Capture completed · captured evidence retrieved"),
  ).toBeVisible();
  for (const width of [390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
  expect(errors).toEqual([]);
});

test("unverified quota and failed retrieval never become useful output", async ({
  page,
}) => {
  const { receipts } = await setup(page, false);
  const failed = {
    ...DETAIL,
    status: "failed",
    pages: [],
    last_error: "public_destination_rejected",
  };
  await page.route("**/api/browserbase/research", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ data: [failed] }),
    });
  });
  await page.route(
    "**/api/browserbase/research/owned-capture",
    async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(failed),
      });
    },
  );
  await page.goto("/workspace/browser-research");
  await page
    .getByLabel("Public HTTPS URLs, one per line")
    .fill("https://openai.com/");
  await expect(
    page.getByRole("button", { name: "Capture pages", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Official docs failed" }).click();
  await expect(page.getByText("Capture failed", { exact: true })).toBeVisible();
  await expect(
    page.getByText("No page evidence has been retrieved."),
  ).toBeVisible();
  await expect(page.getByText(/captured evidence retrieved/)).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Download evidence" }),
  ).toBeDisabled();
  await expect(page.getByText(/Cost unavailable/)).toBeVisible();
  expect(receipts).toHaveLength(0);
});

test("transport ambiguity retries one receipt instead of admitting duplicate work", async ({
  page,
}) => {
  await setup(page);
  const receipts: string[] = [];
  await page.route("**/api/browserbase/research", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        contentType: "application/json",
        body: '{"data":[]}',
      });
      return;
    }
    receipts.push(route.request().headers()["idempotency-key"] ?? "");
    if (receipts.length === 1) await route.abort("failed");
    else
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(DETAIL),
      });
  });
  await page.goto("/workspace/browser-research");
  await page
    .getByLabel("Public HTTPS URLs, one per line")
    .fill("https://openai.com/");
  await page
    .getByRole("button", { name: "Capture pages", exact: true })
    .click();
  await expect(page.getByText(/The request is unconfirmed/)).toBeVisible();
  await expect(
    page.getByLabel("Public HTTPS URLs, one per line"),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Retry same request", exact: true })
    .click();
  await expect(
    page.getByText("Capture completed · captured evidence retrieved"),
  ).toBeVisible();
  expect(receipts).toHaveLength(2);
  expect(receipts[0]).toBe(receipts[1]);
});
