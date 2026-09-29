import { test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.setTimeout(45_000);
test.use({ launchOptions: { executablePath: "/opt/pw-browsers/chromium" } });

const OUT = process.env.SHOT_DIR ?? "shots";
const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";
const SEARCH = /\/api\/(?:langgraph\/)?threads\/search$/;

// The four states the Chats page can open in before it has any chats to show.
const states: Record<string, (page: Page) => Promise<unknown>> = {
  // The read never answers, so the page is caught mid-load.
  loading: (page) =>
    page.route(SEARCH, () => new Promise<void>(() => undefined)),
  error: (page) =>
    page.route(SEARCH, (route) =>
      route.fulfill({ status: 500, json: { detail: "Upstream timed out" } }),
    ),
  empty: async () => undefined,
  "archived-empty": async () => undefined,
};

for (const [w, h, mobile] of [
  [390, 844, true],
  [430, 932, true],
  [1440, 900, false],
] as const) {
  test.describe(`${w}`, () => {
    test.use({
      viewport: { width: w, height: h },
      ...(mobile ? { userAgent: IPHONE, isMobile: true, hasTouch: true } : {}),
    });
    for (const [name, arrange] of Object.entries(states)) {
      test(`chats-${name} ${w}`, async ({ page }) => {
        mockLangGraphAPI(page, { threads: [] });
        await arrange(page);
        await page.goto("/workspace/chats");
        if (name === "archived-empty") {
          await page.getByRole("tab", { name: "Archived" }).click();
        }
        if (name === "error") {
          // The read retries with backoff before it gives up.
          await page
            .getByRole("alert")
            .filter({ hasText: /conversations/ })
            .waitFor({ timeout: 20_000 })
            .catch(() => undefined);
        }
        await page.waitForTimeout(2500);
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - window.innerWidth,
        );
        console.log(`chats-${name} ${w} overflow=${overflow}`);
        await page.screenshot({ path: `${OUT}/chats-${name}-${w}.png` });
      });
    }
  });
}
