import { test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.use({ launchOptions: { executablePath: "/opt/pw-browsers/chromium" } });

const OUT = process.env.SHOT_DIR ?? "shots";
const ago = (m: number) => new Date(Date.now() - m * 60_000).toISOString();
const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";

const run = (i: number, title: string, status: string, m: number, error: string | null = null) => ({
  run_id: `run-${i}`, thread_id: `thread-${i}`, thread_title: title, assistant_id: "dillon-growth", status,
  model_name: "claude-sonnet", created_at: ago(m + 5), updated_at: ago(m), duration_seconds: 240,
  total_tokens: 12_000, message_count: 6, cost: null, error,
});
// A realistic latest page: most work finished, one failure worth seeing.
const RUNS = [
  run(1, "Reconcile September invoices against collected revenue", "running", 1),
  run(2, "Prepare the Fagan Painting onboarding checklist", "pending", 2),
  ...[
    "Draft the Q4 paid search budget memo",
    "Weekly SEO report draft for Acme Landscaping",
    "Summarize Omega's September lead calls",
    "Refresh the Bridge directory sitemap",
    "Answer the KJB review replies",
    "Check Puttery ad spend pacing",
    "Write the Fresh Blends menu launch post",
    "Audit Pro Fence and Deck landing page speed",
    "Tag last week's Hope Wellness inquiries",
    "Draft the Onsite Construction case study outline",
  ].map((t, i) => run(10 + i, t, "success", 30 + i * 90)),
  run(30, "Rebuild the Bridge directory search page", "error", 130, "Build timed out"),
  run(31, "Pull Nexla's campaign export", "interrupted", 400),
];

async function mock(page: Page) {
  mockLangGraphAPI(page, { agents: [] });
  await page.route("**/api/console/stats", (r) =>
    r.fulfill({ json: { total_runs: 14, active_runs: 2, failed_runs: 1, total_threads: 14, total_agents: 0, total_tokens: 168_000, total_cost: null, currency: null } }),
  );
  await page.route(/\/api\/console\/runs(\?|$)/, (r) => r.fulfill({ json: { runs: RUNS, has_more: true } }));
  await page.route(/\/api\/console\/usage/, (r) => r.fulfill({ json: { days: [], by_model: {}, total_tokens: 0, total_runs: 0, total_cost: null, currency: null, attempts: [], has_more: false } }));
}

for (const [w, h, mobile] of [
  [390, 844, true],
  [1440, 900, false],
] as const) {
  test.describe(`${w}`, () => {
    test.use({
      viewport: { width: w, height: h },
      ...(mobile ? { userAgent: IPHONE, isMobile: true, hasTouch: true } : {}),
    });
    test(`board ${w}`, async ({ page }) => {
      await mock(page);
      await page.goto("/workspace/command-center");
      await page.waitForLoadState("networkidle").catch(() => undefined);
      await page.getByRole("heading", { name: "Dispatch board" }).waitFor();
      await page.waitForTimeout(1500);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      // Where the Returned lane starts, measured from the board heading.
      const gap = await page.evaluate(() => {
        const top = (s: string) => document.querySelector(s)!.getBoundingClientRect().top;
        return Math.round(top("#lane-returned") - top("#dispatch-heading"));
      });
      console.log(`board ${w} overflow=${overflow} returnedBelowHeading=${gap}px`);
      await page.locator("#lane-desk").scrollIntoViewIfNeeded();
      await page.locator("#dispatch-heading").evaluate((el) => el.scrollIntoView({ block: "start" }));
      await page.screenshot({ path: `${OUT}/board-${w}.png` });
      await page.locator("#lane-stamped").evaluate((el) => el.scrollIntoView({ block: "start" }));
      await page.waitForTimeout(200);
      await page.screenshot({ path: `${OUT}/board-${w}-2.png` });
      const more = page.getByRole("button", { name: /older stamped/i });
      if (await more.isVisible().catch(() => false)) {
        await more.click();
        await page.waitForTimeout(200);
        await page.screenshot({ path: `${OUT}/board-${w}-open.png` });
      }
    });
  });
}
