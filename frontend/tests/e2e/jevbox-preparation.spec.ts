import { createHash } from "node:crypto";
import { mkdirSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import fixture from "../fixtures/jevbox-preparation.json" with { type: "json" };

import { mockLangGraphAPI } from "./utils/mock-api";

test.use({ serviceWorkers: "block" });
const scope = createHash("sha256")
  .update("synthetic-preparation-scope")
  .digest("hex");

async function setup(page: Page) {
  const state = {
    unavailable: false,
    expired: false,
    malformed: false,
    uploads: [] as string[],
    paidAdmissions: [] as string[],
  };
  await page.route("**/api/**", (route) =>
    route.fulfill({
      status: 404,
      contentType: "application/json",
      body: '{"detail":"fixture_endpoint_unavailable"}',
    }),
  );
  mockLangGraphAPI(page);
  await page.route("**/api/workspaces", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ workspaces: [], active_workspace_id: null }),
    }),
  );
  await page.route("**/api/workflows/**", async (route) => {
    const request = route.request();
    const endpoint = new URL(request.url()).pathname;
    if (endpoint === "/api/workflows/jevbox/status") {
      expect(request.headers()["x-expected-user-id"]).toBe("default");
      await route.fulfill({
        status: state.unavailable ? 409 : 200,
        contentType: "application/json",
        body: JSON.stringify(
          state.unavailable
            ? { detail: "workspace_scope_changed" }
            : {
                owner_scope: scope,
                preparation_available: true,
                current_review: !state.expired,
                dispatch_enabled: false,
              },
        ),
      });
      return;
    }
    if (endpoint === "/api/workflows/jevbox/prepare") {
      expect(request.method()).toBe("POST");
      expect(request.headers()["x-expected-workflow-scope"]).toBe(scope);
      expect(request.headers()["content-type"]).toBe("application/json");
      state.uploads.push(request.postData() ?? "");
      expect(request.postData()).toBe(fixture.packetUtf8);
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          ...fixture.proposal,
          dispatchEnabled: state.malformed,
        }),
      });
      return;
    }
    if (request.method() === "POST") state.paidAdmissions.push(endpoint);
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: '{"detail":"not_enabled"}',
    });
  });
  await page.goto("/workspace/workflows");
  const pane = page.getByRole("region", { name: "Reviewed source draft" });
  await expect(pane.getByLabel("Reviewed JSON file")).toBeVisible();
  return { state, pane };
}

async function upload(page: Page) {
  await page.getByLabel("Reviewed JSON file").setInputFiles({
    name: "synthetic-reviewed-evidence.json",
    mimeType: "application/json",
    buffer: Buffer.from(fixture.packetUtf8),
  });
  await page.getByRole("button", { name: "Prepare unsent draft" }).click();
}

for (const width of [390, 768, 1440]) {
  test(`reviews actual backend fixture with execution disabled at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    const { state, pane } = await setup(page);
    await upload(page);
    await expect(
      pane.getByText("Unsent proposal · synthetic evidence"),
    ).toBeVisible();
    await expect(
      pane.getByText(fixture.proposal.request.inputs.research_question, {
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      pane.getByText(/SYNTHETIC: The heading says October 30/),
    ).toBeVisible();
    expect(state.uploads).toEqual([fixture.packetUtf8]);
    expect(state.paidAdmissions).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    const target = await pane
      .getByRole("button", { name: "Clear file and draft", exact: true })
      .last()
      .boundingBox();
    expect(target?.height).toBeGreaterThanOrEqual(44);
    const shots = process.env.JEVBOX_PREPARATION_SHOTS_DIR;
    if (shots) {
      mkdirSync(shots, { recursive: true });
      await page.screenshot({
        path: path.join(shots, `review-${width}.png`),
        fullPage: true,
      });
    }
    await pane
      .getByRole("button", { name: "Clear file and draft", exact: true })
      .last()
      .click();
    await expect(
      pane.getByText("Unsent proposal · synthetic evidence"),
    ).toHaveCount(0);
  });
}

for (const change of ["unavailable", "expired"] as const) {
  test(`clears a prepared private preview when review becomes ${change}`, async ({
    page,
  }) => {
    const { state, pane } = await setup(page);
    await upload(page);
    await expect(
      pane.getByText("Unsent proposal · synthetic evidence"),
    ).toBeVisible();
    state[change] = true;
    await pane
      .getByRole("button", { name: "Refresh status", exact: true })
      .click();
    await expect(
      pane.getByText("Unsent proposal · synthetic evidence"),
    ).toHaveCount(0);
    await expect(
      pane.getByText(fixture.proposal.request.inputs.research_question, {
        exact: true,
      }),
    ).toHaveCount(0);
    expect(state.uploads).toHaveLength(1);
    expect(state.paidAdmissions).toEqual([]);
  });
}

test("rejects a server response that claims dispatch happened", async ({
  page,
}) => {
  const { state, pane } = await setup(page);
  state.malformed = true;
  await upload(page);
  await expect(pane.getByRole("alert")).toBeVisible();
  await expect(
    pane.getByText("Unsent proposal · synthetic evidence"),
  ).toHaveCount(0);
  expect(state.uploads).toHaveLength(1);
  expect(state.paidAdmissions).toEqual([]);
});
