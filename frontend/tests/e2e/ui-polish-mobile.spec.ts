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

  test("chat controls keep the 44px touch floor on phones", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Touch floor",
          messages: [
            {
              type: "human",
              id: "h1",
              content: [{ type: "text", text: "hi" }],
            },
            { type: "ai", id: "a1", content: "Ready when you are." },
          ],
        },
      ],
    });
    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await page.getByText("Ready when you are.").waitFor();

    // Header, message actions and composer tools: tooltip-wrapped buttons
    // used to slip past the phone rule at 32px.
    const small = await page.evaluate(() =>
      [
        ...document.querySelectorAll(
          "[data-chat-header] button, [data-chat-header] a, [data-chat-composer] button, [data-testid='main-message-list'] button",
        ),
      ]
        .filter((el) => (el as HTMLElement).offsetParent)
        .map((el) => {
          const b = el.getBoundingClientRect();
          return {
            label: el.getAttribute("aria-label"),
            w: b.width,
            h: b.height,
          };
        })
        .filter((b) => b.w < 44 || b.h < 44),
    );
    expect(small).toEqual([]);

    // The thread's Scheduled tasks link folds into Chat actions.
    await expect(
      page
        .locator("[data-chat-header]")
        .getByRole("link", { name: "Scheduled tasks" }),
    ).toBeHidden();
    await expect(async () => {
      await page.getByRole("button", { name: "Chat actions" }).click();
      await expect(
        page.getByRole("menuitem", { name: "Scheduled tasks" }),
      ).toHaveAttribute(
        "href",
        `/workspace/scheduled-tasks?thread_id=${MOCK_THREAD_ID}`,
        { timeout: 1_000 },
      );
    }).toPass();
    await expect(
      page.getByRole("menuitem", { name: "Export as Markdown" }),
    ).toBeVisible();
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
