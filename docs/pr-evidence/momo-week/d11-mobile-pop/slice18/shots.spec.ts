import { test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.use({ launchOptions: { executablePath: "/opt/pw-browsers/chromium" } });

// Slice 18 evidence: a project's Chats tab files its chats like the Chats
// page. Run from frontend/ with this file copied into tests/e2e and SHOT_DIR set.
const OUT = process.env.SHOT_DIR ?? "shots";
const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";
const P = "11111111-1111-4111-8111-111111111111";
// Fixed local wall-clock times so the shots read the same on every run.
const day = (offset: number, hh: number, mm = 0) => {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  d.setHours(hh, mm, 0, 0);
  return d.toISOString();
};
const THREADS = [
  ["Draft the September SEO report for the Bucks County service pages", day(0, 0, 40)],
  ["Fix the broken contact form redirect on mobile Safari", day(-1, 16, 5)],
  ["Summarize last week's call notes", day(-3, 11, 20)],
  ["Rewrite the spring cleanup landing page so it leads with the free estimate", day(-12, 9, 45)],
  ["Audit Google Business Profile reviews", day(-48, 14, 0)],
].map(([title, at], i) => ({
  thread_id: `t${i}`,
  title,
  updated_at: at,
  metadata: { deerflow_project_id: P },
}));

for (const [w, h, mobile] of [[390, 844, true], [430, 932, true], [1440, 900, false]] as const) {
  test.describe(`${w}`, () => {
    test.use({ viewport: { width: w, height: h }, ...(mobile ? { userAgent: IPHONE, isMobile: true, hasTouch: true } : {}) });
    test(`project chats ${w}`, async ({ page }) => {
      mockLangGraphAPI(page, {
        projects: [{ id: P, name: "Acme Landscaping retainer", instructions: "Write for homeowners in Bucks County." }],
        threads: THREADS as never,
      });
      await page.goto(`/workspace/projects/${P}`);
      await page.getByRole("link", { name: /Draft the September/ }).first().waitFor();
      await page.waitForTimeout(1200);
      await page.screenshot({ path: `${OUT}/project-chats-${w}.png` });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      const rows = await page.evaluate(() =>
        [...document.querySelectorAll("a[href^='/workspace/chats/']")]
          .filter((a) => a.closest("main, [data-slot='scroll-area-viewport']"))
          .map((a) => { const r = a.getBoundingClientRect(); return `${Math.round(r.height)}px ${(a as HTMLElement).innerText.replace(/\n/g, " | ")}`; }),
      );
      console.log(`FACTS ${w} overflow=${overflow} ${JSON.stringify(rows)}`);
    });
  });
}
