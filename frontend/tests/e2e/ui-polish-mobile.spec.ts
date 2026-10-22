import { expect, test } from "@playwright/test";

import { MOCK_THREAD_ID, mockLangGraphAPI } from "./utils/mock-api";

test.describe("UI polish mobile regressions", () => {
  test("workspace exposes mobile sidebar navigation from the chat header", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");

    // A click that lands before hydration does nothing (the button is server
    // rendered), and this raced on the trunk too: retry until the sheet opens.
    await expect(async () => {
      await page.getByRole("button", { name: /toggle sidebar/i }).click();
      await expect(page.getByRole("link", { name: /new chat/i })).toBeVisible({
        timeout: 1_000,
      });
    }).toPass();
    await expect(page.getByRole("link", { name: /agents/i })).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
      .toBeLessThanOrEqual(375);
  });

  test("mobile sidebar closes after following a navigation link", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");

    await expect(async () => {
      await page.locator("[data-sidebar='trigger']:visible").first().click();
      await expect(
        page.locator("[data-mobile='true'][data-sidebar='sidebar']"),
      ).toBeVisible({ timeout: 1_000 });
    }).toPass();

    const mobileSidebar = page.locator(
      "[data-mobile='true'][data-sidebar='sidebar']",
    );
    await mobileSidebar
      .getByRole("link", { name: "Chats", exact: true })
      .click();

    await expect(page).toHaveURL(/\/workspace\/chats$/);
    await expect(mobileSidebar).toBeHidden();
  });

  test("mobile sidebar closes after query-only navigation", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new?source=mobile");

    await expect(async () => {
      await page.locator("[data-sidebar='trigger']:visible").first().click();
      await expect(
        page.locator("[data-mobile='true'][data-sidebar='sidebar']"),
      ).toBeVisible({ timeout: 1_000 });
    }).toPass();

    const mobileSidebar = page.locator(
      "[data-mobile='true'][data-sidebar='sidebar']",
    );
    await mobileSidebar
      .getByRole("link", { name: "New chat", exact: true })
      .click();

    await expect(page).toHaveURL(/\/workspace\/chats\/new$/);
    await expect(mobileSidebar).toBeHidden();
  });

  test("mobile sidebar closes after activating the current workspace link", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");

    await expect(async () => {
      await page.locator("[data-sidebar='trigger']:visible").first().click();
      await expect(
        page.locator("[data-mobile='true'][data-sidebar='sidebar']"),
      ).toBeVisible({ timeout: 1_000 });
    }).toPass();

    const mobileSidebar = page.locator(
      "[data-mobile='true'][data-sidebar='sidebar']",
    );
    await mobileSidebar
      .getByRole("link", { name: "New chat", exact: true })
      .click();

    await expect(page).toHaveURL(/\/workspace\/chats\/new$/);
    await expect(mobileSidebar).toBeHidden();
  });

  test("mobile sidebar stays closed after crossing the desktop breakpoint", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");

    await expect(async () => {
      await page.locator("[data-sidebar='trigger']:visible").first().click();
      await expect(
        page.locator("[data-mobile='true'][data-sidebar='sidebar']"),
      ).toBeVisible({ timeout: 1_000 });
    }).toPass();

    const mobileSidebar = page.locator(
      "[data-mobile='true'][data-sidebar='sidebar']",
    );
    await page.setViewportSize({ width: 820, height: 844 });
    await expect(mobileSidebar).toBeHidden();
    await page.setViewportSize({ width: 390, height: 844 });

    await expect(mobileSidebar).toBeHidden();
  });

  test("mobile sidebar keeps recent chats visible when desktop sidebar is collapsed", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Recent phone chat",
        },
      ],
    });

    await page.goto("/workspace/chats/new");
    await page.evaluate(() => {
      document.cookie = "sidebar_state=false; path=/; max-age=604800";
    });
    await page.reload();

    await expect(async () => {
      await page.locator("[data-sidebar='trigger']:visible").first().click();
      await expect(
        page.locator("[data-mobile='true'][data-sidebar='sidebar']"),
      ).toBeVisible({ timeout: 1_000 });
    }).toPass();

    const mobileSidebar = page.locator(
      "[data-mobile='true'][data-sidebar='sidebar']",
    );
    await expect(
      mobileSidebar.locator(`a[href='/workspace/chats/${MOCK_THREAD_ID}']`),
    ).toBeVisible();
    await expect(
      mobileSidebar.getByRole("button", { name: /settings and more/i }),
    ).toBeVisible();
    await page.screenshot({
      path: test.info().outputPath("mobile-sidebar.png"),
      animations: "disabled",
    });

    await mobileSidebar
      .locator(`a[href='/workspace/chats/${MOCK_THREAD_ID}']`)
      .click();
    await expect(page).toHaveURL(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(mobileSidebar).toBeHidden();
  });

  test("mobile artifacts open in a drawer without horizontal overflow", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Thread with artifact",
          artifacts: ["reports/mobile-summary.md"],
        },
      ],
    });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await page.getByTestId("artifact-trigger").click();

    await expect(
      page.getByRole("dialog", { name: /artifacts/i }),
    ).toBeVisible();
    await expect(page.getByText("mobile-summary.md")).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
      .toBeLessThanOrEqual(375);
  });

  test("global focus ring tokens are visible in light and dark themes", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await page.goto("/workspace/chats/new");

    const readRing = () =>
      page.evaluate(() =>
        getComputedStyle(document.documentElement)
          .getPropertyValue("--ring")
          .trim(),
      );

    await page.evaluate(() =>
      document.documentElement.classList.remove("dark"),
    );
    const lightRing = await readRing();
    expect(lightRing).not.toBe("transparent");
    expect(lightRing).not.toBe("");

    await page.evaluate(() => document.documentElement.classList.add("dark"));
    const darkRing = await readRing();
    expect(darkRing).not.toBe("transparent");
    expect(darkRing).not.toBe("");

    // The two themes must resolve to different ring tokens, otherwise the test
    // would pass trivially if <html> were stuck in one mode.
    expect(darkRing).not.toBe(lightRing);
  });

  test("chats search and tabs keep the page gutter on phones", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats");

    const search = page.getByPlaceholder("Search chats");
    await expect(search).toBeVisible();
    const bounds = await search.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(12);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390 - 12);
  });

  test("?settings=security opens the Security section", async ({ page }) => {
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new?settings=security");

    const dialog = page.getByRole("dialog", { name: "Settings" });
    await expect(
      dialog.getByRole("button", { name: "Security", exact: true }),
    ).toHaveAttribute("aria-current", "page");
    await expect(
      dialog.getByRole("heading", { name: "Two-factor authentication" }),
    ).toBeVisible();
  });
});
