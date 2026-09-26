import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

// Matches appearanceKey("default") in
// components/workspace/command-center/appearance-preferences.ts — "default"
// is MOCK_AUTH_USER.id in mock-api.ts.
const APPEARANCE_STORAGE_KEY = "momentum:appearance:v1:default";

test.describe("Agents page under the retro appearance treatment", () => {
  test("survives /api/features failing while the retro pixelation resolve is in flight", async ({
    page,
  }) => {
    // Store the appearance preference the way the app itself does
    // (AccountAppearance in appearance-provider.tsx reads this key), via
    // addInitScript so it exists before any app script runs and
    // RetroResolve is active from the very first paint of the route.
    await page.addInitScript(
      ([key, value]) => window.localStorage.setItem(key, value),
      [
        APPEARANCE_STORAGE_KEY,
        JSON.stringify({
          treatment: "retro",
          motion: true,
          logo: null,
          label: "",
        }),
      ] as const,
    );

    mockLangGraphAPI(page, { agents: [] });

    // Reproduce the console evidence: an agents-related endpoint answers
    // with a Bad Gateway just as the page loads. /api/features gates
    // AgentsLayout's entire top-level subtree (loading vs. feature-disabled
    // vs. the real page), so a fast failure here forces that swap to
    // happen almost immediately after mount, deep inside RetroResolve's
    // ~600ms pixelation window.
    await page.route("**/api/features", (route) =>
      route.fulfill({
        status: 502,
        contentType: "text/plain",
        body: "Bad Gateway",
      }),
    );

    const pageErrors: string[] = [];
    page.on("pageerror", (err) => pageErrors.push(err.message));
    const consoleErrors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });

    await page.goto("/workspace/agents");

    // The real Agents page must render — not Next's built-in root error
    // fallback ("This page couldn't load" / "Reload to try again, or go
    // back."), which is what an uncaught commit-phase exception produces
    // when nothing in the tree defines error.tsx / global-error.tsx.
    await expect(page.getByRole("heading", { name: "Agents" })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText(/this page couldn.t load/i)).toHaveCount(0);

    expect(pageErrors).toEqual([]);
    expect(
      consoleErrors.filter((message) =>
        /removeChild|insertBefore|NotFoundError|not a child of this node/i.test(
          message,
        ),
      ),
    ).toEqual([]);
  });
});
