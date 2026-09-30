import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.describe("Landing page", () => {
  test("renders the header and hero section", async ({ page }) => {
    await page.goto("/");

    await expect(
      page
        .getByRole("banner")
        .getByRole("link", { name: "MomoBot", exact: true }),
    ).toBeVisible();
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(
      page.getByRole("heading", { name: "Say hello to MomoBot", exact: true }),
    ).toBeVisible();

    // Current MomoBot call to action in the hero.
    await expect(
      page.getByRole("link", { name: "Enter the workspace", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Enter the workspace", exact: true }),
    ).toHaveAttribute("href", "/workspace");
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

  test("Enter the workspace link navigates to workspace", async ({ page }) => {
    mockLangGraphAPI(page);

    await page.goto("/");

    const enterWorkspace = page.getByRole("link", {
      name: "Enter the workspace",
      exact: true,
    });
    await expect(enterWorkspace).toHaveAttribute("href", "/workspace");
    await enterWorkspace.click();

    // The default workspace home is Command Center when Desk is disabled.
    await expect(page).toHaveURL(
      new URL("/workspace/command-center", page.url()).href,
    );
    await expect(
      page.getByRole("heading", { name: "Mission Control", exact: true }),
    ).toBeVisible();
  });
});
