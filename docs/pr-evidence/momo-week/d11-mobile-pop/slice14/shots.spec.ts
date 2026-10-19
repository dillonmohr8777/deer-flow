import { test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.setTimeout(45_000);
test.use({ launchOptions: { executablePath: "/opt/pw-browsers/chromium" } });

const OUT = process.env.SHOT_DIR ?? "shots";
const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";

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

    test(`chat-new ${w}`, async ({ page }) => {
      mockLangGraphAPI(page, { threads: [] });
      await page.goto("/workspace/chats/new");
      await page.waitForTimeout(2500);
      // Where the thumb has to reach: the composer's field and the starters.
      const m = await page.evaluate(() => {
        const box = (el: Element | null) => el?.getBoundingClientRect();
        const field = box(document.querySelector("textarea"));
        const starters = [
          ...document.querySelectorAll("[data-chat-starters] button"),
        ].map((b) => {
          const r = b.getBoundingClientRect();
          return `${Math.round(r.height)}h/${getComputedStyle(b).borderRadius}`;
        });
        return {
          overflow: document.documentElement.scrollWidth - window.innerWidth,
          fieldTop: Math.round(field?.top ?? -1),
          fieldBottom: Math.round(field?.bottom ?? -1),
          starters,
        };
      });
      console.log(`chat-new ${w} ${JSON.stringify(m)}`);
      await page.screenshot({ path: `${OUT}/chat-new-${w}.png` });
    });

  });
}
