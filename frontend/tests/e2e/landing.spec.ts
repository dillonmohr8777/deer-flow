import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.describe("Landing page", () => {
  test("renders the header and hero section", async ({ page }) => {
    await page.goto("/");

    await expect(
      page
        .locator("header")
        .first()
        .getByRole("img", { name: "Momentum", exact: true }),
    ).toBeVisible();
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.locator("h1")).toHaveText(
      /^The future needs\s*Momentum$/,
    );

    // "Enter the workspace" call-to-action button in hero
    await expect(
      page.getByRole("link", { name: /enter the workspace/i }),
    ).toBeVisible();
  });

  for (const width of [320, 375, 390]) {
    test(`does not overflow at ${width}px width`, async ({ page }) => {
      await page.setViewportSize({ width, height: 812 });
      await page.goto("/");

      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
        .toBeLessThanOrEqual(width);
      await expect(page.locator("main").first()).toBeInViewport();
    });
  }

  test("Enter the workspace link navigates to command center", async ({
    page,
  }) => {
    mockLangGraphAPI(page);

    await page.goto("/");

    const enterWorkspace = page.getByRole("link", {
      name: /enter the workspace/i,
    });
    await enterWorkspace.click();

    // Should redirect to /workspace/command-center
    await page.waitForURL("**/workspace/command-center");
    await expect(page).toHaveURL(/\/workspace\/command-center/);
  });
});
