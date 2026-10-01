import { test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.use({ launchOptions: { executablePath: "/opt/pw-browsers/chromium" } });

// Slice 17 evidence: Scheduled tasks say when in words. Run from frontend/ with
// this file copied into tests/e2e and SHOT_DIR set.
const OUT = process.env.SHOT_DIR ?? "shots";
const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";

// Fixed local wall-clock times so the shots read the same on every run.
const day = (offset: number, hh: number, mm = 0) => {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  d.setHours(hh, mm, 0, 0);
  return d.toISOString();
};
const task = (id: string, title: string, next: string | null, last: string | null, err: string | null = null, status = "enabled") => ({
  id, thread_id: null, context_mode: "fresh_thread_per_run", assistant_id: null, title, prompt: "", schedule_type: "cron",
  schedule_spec: {}, timezone: "UTC", status, next_run_at: next, last_run_at: last, last_run_id: last ? "r" + id : null,
  last_thread_id: last ? "thread-" + id : null, last_error: err, run_count: last ? 3 : 0, created_at: day(-30, 9), updated_at: day(-1, 9),
});
const TASKS = [
  task("a", "Weekly SEO report draft for Acme Landscaping", day(1, 8, 50), day(-6, 8, 50)),
  task("b", "Monday ad spend check", day(0, 23, 30), day(-1, 9, 0), "Google Ads token expired, reconnect the account"),
  task("c", "Review replies waiting in the inbox", day(3, 14, 0), day(0, 0, 5)),
  task("d", "Quarterly review deck for Bridge", day(40, 10, 0), null),
  task("e", "Old launch checklist", null, day(-45, 16, 0), null, "paused"),
];
const RUNS = [0, 1, 2].map((i) => ({
  id: "run-" + i, task_id: "a", run_id: "lg-" + i, thread_id: "thread-a", trigger: "scheduled", attempt_count: 1, status: i === 1 ? "failed" : "success",
  scheduled_for: day(-7 * (i + 1) + 1, 8, 50), started_at: day(-7 * (i + 1) + 1, 8, 50), finished_at: day(-7 * (i + 1) + 1, 8, 52),
  error: i === 1 ? "Search Console quota exceeded" : null, created_at: day(-7 * (i + 1) + 1, 8, 50),
}));

async function mock(page: Page) {
  mockLangGraphAPI(page, { scheduledTasks: TASKS as never, threads: [] as never, agents: [] as never });
  await page.route("**/api/scheduled-tasks/*/runs**", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(RUNS) }),
  );
}

for (const [w, h, mobile] of [[390, 844, true], [430, 932, true], [1440, 900, false]] as const) {
  test.describe(`${w}`, () => {
    test.use({ viewport: { width: w, height: h }, ...(mobile ? { userAgent: IPHONE, isMobile: true, hasTouch: true } : {}) });
    test(`scheduled times ${w}`, async ({ page }) => {
      await mock(page);
      await page.goto("/workspace/scheduled-tasks");
      await page.getByTestId("scheduled-task-item-a").waitFor();
      await page.waitForTimeout(1500);
      await page.screenshot({ path: `${OUT}/scheduled-${w}.png` });
      await page.getByTestId("scheduled-task-item-a").click();
      await page.waitForTimeout(1200);
      await page.screenshot({ path: `${OUT}/scheduled-${w}-detail.png` });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      const rows = await page.evaluate(() =>
        [...document.querySelectorAll("[data-testid^='scheduled-task-item-']")].map((b) => (b as HTMLElement).innerText.replace(/\n/g, " | ")),
      );
      console.log(`FACTS ${w} overflow=${overflow} ${JSON.stringify(rows)}`);
    });
  });
}
