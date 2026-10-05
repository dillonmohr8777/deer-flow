import { test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.use({ launchOptions: { executablePath: "/opt/pw-browsers/chromium" } });

const OUT = process.env.SHOT_DIR ?? "shots";
const task = (id: string, title: string, extra = {}) => ({
  id,
  thread_id: null,
  title,
  prompt: "Draft it and cite the source.",
  schedule_type: "cron" as const,
  schedule_spec: { cron: "0 9 * * *" },
  timezone: "UTC",
  status: "enabled" as const,
  next_run_at: null,
  last_run_at: null,
  last_run_id: null,
  last_error: null,
  run_count: 0,
  context_mode: "fresh_thread_per_run" as const,
  assistant_id: null,
  created_at: "2026-09-30T09:00:00Z",
  updated_at: "2026-09-30T09:00:00Z",
  ...extra,
});

for (const [w, h] of [
  [390, 844],
  [1440, 900],
] as const) {
  test.describe(`${w}`, () => {
    test.use({ viewport: { width: w, height: h } });
    test(`filters ${w}`, async ({ page }) => {
      mockLangGraphAPI(page, {
        threads: [],
        scheduledTasks: [
          task("a", "Weekly SEO report draft"),
          task("b", "Monday ad spend check", {
            last_error: "Google Ads token expired, reconnect the account",
          }),
        ],
      });
      await page.goto("/workspace/scheduled-tasks");
      await page.getByTestId("scheduled-task-item-b").waitFor();
      await page.waitForTimeout(800);
      const pressed = page.locator("[aria-pressed='true']").first();
      const facts = await pressed.evaluate((el) => {
        const s = getComputedStyle(el);
        return { color: s.color, bg: s.backgroundColor, text: el.textContent };
      });
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      console.log(`tasks ${w} ${JSON.stringify(facts)} overflow=${overflow}`);
      await page.screenshot({ path: `${OUT}/tasks-${w}.png` });
      await pressed.focus();
      await page.keyboard.press("Tab");
      await page.keyboard.press("Shift+Tab");
      await page.screenshot({ path: `${OUT}/tasks-focus-${w}.png` });

      await page.goto("/workspace/capabilities");
      await page.waitForTimeout(2500);
      await page.screenshot({ path: `${OUT}/capabilities-${w}.png` });
    });
  });
}
