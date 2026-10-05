import { test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.use({ launchOptions: { executablePath: "/opt/pw-browsers/chromium" } });

const OUT = process.env.SHOT_DIR ?? "shots";
const ago = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString();
const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";

const threads = [
  { thread_id: "c1", title: "Draft the October content calendar for Acme Landscaping", updated_at: ago(0.3), metadata: { deerflow_project_id: "p1" } },
  { thread_id: "c2", title: "Why did cost per lead jump on the spring cleanup campaign last week, and what should we change before Friday's report?", updated_at: ago(3) },
  { thread_id: "c3", title: "Client asked about the new landing page copy", updated_at: ago(26), metadata: { channel_source: { type: "im_channel", provider: "slack" } } },
  { thread_id: "c4", title: "Summarize the Q3 SEO audit", updated_at: ago(50), metadata: { deerflow_project_id: "p1" } },
  { thread_id: "c5", title: "Settled chat", updated_at: ago(24 * 9) },
];

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
    for (const empty of [false, true]) {
      const name = empty ? "chats-empty" : "chats";
      test(`${name} ${w}`, async ({ page }) => {
        mockLangGraphAPI(page, {
          threads: empty ? [] : (threads as never),
          projects: [{ id: "p1", name: "Acme Landscaping" }],
        });
        await page.goto("/workspace/chats");
        await page.waitForLoadState("networkidle").catch(() => undefined);
        await page.waitForTimeout(2500);
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - window.innerWidth,
        );
        console.log(`${name} ${w} overflow=${overflow}`);
        await page.screenshot({ path: `${OUT}/${name}-${w}.png` });
      });
    }
  });
}
