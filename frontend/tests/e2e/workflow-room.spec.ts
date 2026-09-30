import { createHash } from "node:crypto";
import { mkdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { type WorkflowRun } from "../../src/core/workflows/types";
import {
  WORKFLOW_FIXTURES,
  WORKFLOW_RUN,
  WORKFLOW_STATUS,
} from "../fixtures/workflows";

import { mockLangGraphAPI } from "./utils/mock-api";

// Interception must never be bypassed by an existing authenticated worker.
test.use({ serviceWorkers: "block" });
const ARTIFACT = JSON.stringify({
  accepted: true,
  result: "Synthetic accepted workflow fixture",
});
const COMPLETED: WorkflowRun = {
  ...WORKFLOW_RUN,
  artifact: {
    bytes: Buffer.byteLength(ARTIFACT),
    sha256: createHash("sha256").update(ARTIFACT).digest("hex"),
  },
};

async function setup(
  page: Page,
  options: {
    ambiguous?: boolean;
    unavailable?: boolean;
    interrupted?: boolean;
    corruptArtifact?: boolean;
  } = {},
) {
  // No unhandled app API can escape fixture QA and reach a live provider.
  await page.route("**/api/**", (route) =>
    route.fulfill({
      status: 404,
      contentType: "application/json",
      body: '{"detail":"fixture_endpoint_unavailable"}',
    }),
  );
  mockLangGraphAPI(page);
  const state = {
    saved: !!options.interrupted,
    run: options.interrupted
      ? {
          ...COMPLETED,
          status: "interrupted" as const,
          accepted: false,
          output: null,
          artifact: null,
        }
      : COMPLETED,
    receipts: [] as string[],
    payloads: [] as unknown[],
    actions: [] as string[],
  };
  await page.route("**/api/workflows/**", async (route) => {
    const request = route.request(),
      endpoint = new URL(request.url()).pathname;
    expect(
      request.headers()[
        endpoint.endsWith("/status")
          ? "x-expected-user-id"
          : "x-expected-workflow-scope"
      ],
    ).toBe(endpoint.endsWith("/status") ? "default" : "scope-one");
    if (endpoint.endsWith("/artifact")) {
      await route.fulfill({
        contentType: "application/json",
        headers: {
          "Content-Disposition": 'attachment; filename="workflow.json"',
        },
        body: options.corruptArtifact
          ? ARTIFACT.replace("accepted", "rejected")
          : ARTIFACT,
      });
      return;
    }
    let body: unknown;
    if (endpoint.endsWith("/status"))
      body = { ...WORKFLOW_STATUS, enabled: !options.unavailable };
    else if (endpoint.endsWith("/catalog"))
      body = { workflows: WORKFLOW_FIXTURES, total: WORKFLOW_FIXTURES.length };
    else if (endpoint.endsWith("/runs") && request.method() === "GET")
      body = { runs: state.saved ? [state.run] : [] };
    else if (endpoint.endsWith("/runs") && request.method() === "POST") {
      state.receipts.push(request.headers()["idempotency-key"] ?? "");
      state.payloads.push(request.postDataJSON());
      state.saved = true;
      if (options.ambiguous && state.receipts.length === 1) {
        await route.fulfill({
          status: 502,
          contentType: "application/json",
          body: '{"detail":"provider_outcome_unknown"}',
        });
        return;
      }
      state.run = COMPLETED;
      body = state.run;
    } else if (request.method() === "POST") {
      state.actions.push(endpoint);
      state.run = endpoint.endsWith("/cancel")
        ? {
            ...COMPLETED,
            status: "cancelled",
            accepted: false,
            output: null,
            artifact: null,
          }
        : COMPLETED;
      body = state.run;
    } else body = state.run;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
  return state;
}
async function choose(page: Page, number = "001") {
  await page
    .getByRole("button", { name: new RegExp(`^Synthetic workflow ${number}`) })
    .click();
}

test("catalog search, editable synthetic inputs and accepted artifact survive reopening on phone", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 390, height: 1000 });
  const state = await setup(page);
  await page.goto("/workspace/workflows");
  await expect(
    page.getByRole("heading", { name: "Workflow room", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("100 of 100 workflow definitions")).toBeVisible();
  await page.getByLabel("Workflow category").selectOption("Operations");
  await page.getByLabel("Search workflows").fill("099");
  await expect(page.getByText("1 of 100 workflow definitions")).toBeVisible();
  await choose(page, "099");
  await page.getByRole("button", { name: "Load synthetic example" }).click();
  await expect(page.getByText(/Synthetic example loaded/)).toBeVisible();
  await page
    .getByLabel("Task brief (required)")
    .fill("Actual edited fixture task");
  await expect(
    page.getByRole("option", { name: "CrewAI (unavailable)" }),
  ).toBeDisabled();
  expect(state.receipts).toEqual([]);
  await page.getByRole("button", { name: "Run workflow", exact: true }).click();
  await expect(
    page.getByText("completed · LangGraph · acceptance passed"),
  ).toBeVisible();
  await expect(page.getByText(/Cost unavailable/)).toBeVisible();
  expect(state.payloads[0]).toEqual(
    expect.objectContaining({
      workflow_id: "fixture-099",
      inputs: expect.objectContaining({ brief: "Actual edited fixture task" }),
      framework: "langgraph",
    }),
  );
  expect(
    await page.evaluate(
      () =>
        (window as unknown as { __workflowScriptRan?: boolean })
          .__workflowScriptRan,
    ),
  ).toBeUndefined();
  const downloading = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download accepted artifact" })
    .click();
  const download = await downloading;
  const saved = await download.path();
  expect(saved).not.toBeNull();
  expect(readFileSync(saved, "utf8")).toBe(ARTIFACT);
  await expect(page.getByText(/size and SHA-256 matched/)).toBeVisible();
  await page.reload();
  await page
    .getByRole("button", { name: /^Synthetic saved run completed/ })
    .click();
  await expect(
    page.getByText("completed · LangGraph · acceptance passed"),
  ).toBeVisible();
  expect(state.receipts).toHaveLength(1);
  expect(errors).toEqual([]);
});

test("unconfirmed admission retries the same exact request and receipt", async ({
  page,
}) => {
  const state = await setup(page, { ambiguous: true });
  await page.goto("/workspace/workflows");
  await choose(page);
  await page.getByLabel("Task brief (required)").fill("Bounded fixture task");
  await page.getByRole("button", { name: "Run workflow", exact: true }).click();
  await expect(page.getByText(/request is unconfirmed/)).toBeVisible();
  await expect(page.getByLabel("Task brief (required)")).toBeDisabled();
  await page.getByRole("button", { name: "Retry same request" }).click();
  await expect(page.getByText(/acceptance passed/)).toBeVisible();
  expect(state.receipts).toHaveLength(2);
  expect(new Set(state.receipts).size).toBe(1);
  expect(state.payloads[0]).toEqual(state.payloads[1]);
});

test("disabled execution cannot admit work or advertise it as complete", async ({
  page,
}) => {
  const state = await setup(page, { unavailable: true });
  await page.goto("/workspace/workflows");
  await choose(page);
  await page.getByLabel("Task brief (required)").fill("No paid dispatch");
  await expect(
    page.getByRole("button", { name: "Run workflow", exact: true }),
  ).toBeDisabled();
  await expect(page.getByText("Workflow execution is disabled.")).toBeVisible();
  expect(state.receipts).toEqual([]);
  await expect(
    page.getByRole("button", { name: "Download accepted artifact" }),
  ).toHaveCount(0);
});

test("interrupted resume uses the existing record and original budget", async ({
  page,
}) => {
  const state = await setup(page, { interrupted: true });
  await page.goto("/workspace/workflows");
  await page
    .getByRole("button", { name: /^Synthetic saved run interrupted/ })
    .click();
  await expect(page.getByText(/remaining budget/)).toBeVisible();
  await page.getByRole("button", { name: "Resume interrupted run" }).click();
  await expect(page.getByText(/acceptance passed/)).toBeVisible();
  expect(state.actions).toEqual(["/api/workflows/runs/owned-run/resume"]);
  expect(state.receipts).toEqual([]);
});

test("altered artifact bytes never become a successful download", async ({
  page,
}) => {
  const state = await setup(page, { corruptArtifact: true });
  await page.goto("/workspace/workflows");
  await choose(page);
  await page
    .getByLabel("Task brief (required)")
    .fill("Download integrity fixture");
  await page.getByRole("button", { name: "Run workflow", exact: true }).click();
  let downloads = 0;
  page.on("download", () => (downloads += 1));
  await page
    .getByRole("button", { name: "Download accepted artifact" })
    .click();
  await expect(page.getByText(/artifact hash does not match/)).toBeVisible();
  expect(downloads).toBe(0);
  expect(state.receipts).toHaveLength(1);
});

for (const width of [390, 768, 1440])
  test(`workflow inputs fit${width}px with44px controls and reduced motion`, async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setViewportSize({ width, height: 1000 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await setup(page);
    await page.goto("/workspace/workflows");
    await choose(page);
    await page.getByRole("button", { name: "Load synthetic example" }).click();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    const controls = page.locator("main").getByRole("button");
    for (const button of await controls.all()) {
      if (await button.isVisible()) {
        const box = await button.boundingBox();
        expect(box?.height).toBeGreaterThanOrEqual(44);
        expect(box?.width).toBeGreaterThanOrEqual(44);
        const durations = await button.evaluate((element) =>
          getComputedStyle(element)
            .transitionDuration.split(",")
            .map(parseFloat),
        );
        // The app's accessibility rule uses a negligible 0.01 ms transition.
        expect(Math.max(...durations)).toBeLessThanOrEqual(0.00002);
      }
    }
    await page.getByLabel("Task brief (required)").focus();
    await expect(page.getByLabel("Task brief (required)")).toBeFocused();
    expect(errors).toEqual([]);
    const shots =
      process.env.WORKFLOW_SHOTS_DIR ?? "/tmp/momobot-workflow-ui-qa";
    mkdirSync(shots, { recursive: true });
    await page.screenshot({
      path: path.join(shots, `workflow-${width}.png`),
      fullPage: false,
    });
  });
