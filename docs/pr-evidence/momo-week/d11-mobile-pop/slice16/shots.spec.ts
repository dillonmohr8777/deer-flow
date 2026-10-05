import { test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.use({ launchOptions: { executablePath: "/opt/pw-browsers/chromium" } });

const OUT = process.env.SHOT_DIR ?? "shots";
const at = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString();
const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});
const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";

const template = (id: string, name: string, model: string) => ({
  id, version: "1", name, description: "", model, skills: [], tool_groups: [], mcp_plugins: [],
  schedule: { cron: "0 9 * * 1", timezone: "UTC" }, acceptance_criteria: [],
});
const TEMPLATES = [
  template("chief-of-staff", "Chief of staff", "claude-sonnet"),
  template("delivery-auditor", "Delivery auditor", "claude-sonnet"),
  template("research-swarm", "Research swarm", "claude-sonnet"),
  template("muse-scout", "Muse scout", "claude-sonnet"),
  template("marketing-lead", "Marketing lead", "claude-sonnet"),
  template("seo-geo-strategist", "SEO and GEO strategist", "claude-sonnet"),
  template("eng-lead", "Engineering lead", "claude-sonnet"),
  template("qa-critic", "QA critic", "claude-sonnet"),
  template("web-builder", "Web builder", "claude-sonnet"),
  template("momo-concierge", "Momo concierge", "claude-sonnet"),
  template("client-reporter", "Client reporter", "claude-sonnet"),
  template("revenue-ops", "Revenue ops", "claude-sonnet"),
];
const task = (id: string, agent: string, title: string, h: number, err: string | null = null) => ({
  id, thread_id: null, context_mode: "fresh_thread_per_run", assistant_id: agent, title, prompt: "", schedule_type: "cron",
  schedule_spec: {}, timezone: "UTC", status: "enabled", next_run_at: at(20), last_run_at: at(h), last_run_id: "r" + id,
  last_thread_id: "thread-" + id, last_error: err, run_count: 3, created_at: at(-300), updated_at: at(h),
});
const TASKS = [
  task("a", "seo-geo-strategist", "Weekly SEO report draft", -30),
  task("b", "revenue-ops", "Monday pipeline check", -50, "CRM token expired"),
  task("c", "client-reporter", "Monthly client report", -80),
];

async function mock(page: Page) {
  mockLangGraphAPI(page, { scheduledTasks: TASKS as never, threads: [] as never, agents: [] });
  await page.route("**/api/features", (r) =>
    r.fulfill(json({ agents_api: { enabled: true }, desk: { enabled: true } })),
  );
  await page.route("**/api/fleet/templates", (r) => r.fulfill(json({ templates: TEMPLATES })));
  await page.route("**/api/clients", (r) => r.fulfill(json({ clients: [] })));
  await page.route("**/api/board/threads**", (r) => r.fulfill(json({ threads: [] })));
}

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
    test(`desk-agents ${w}`, async ({ page }) => {
      await mock(page);
      await page.goto("/workspace/desk");
      await page.waitForLoadState("networkidle").catch(() => undefined);
      await page.waitForTimeout(2500);
      const section = page.locator("#desk-agents").locator("xpath=ancestor::section[1]");
      await page.locator("#desk-agents").scrollIntoViewIfNeeded();
      await page.locator("#desk-agents").evaluate((el) => el.scrollIntoView({ block: "start" }));
      await page.waitForTimeout(400);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      const rows = await section.locator("li").evaluateAll((els) =>
        els.slice(0, 3).map((el) => Math.round(el.getBoundingClientRect().height)),
      );
      console.log(`desk-agents ${w} overflow=${overflow} rowHeights=${JSON.stringify(rows)}`);
      await page.screenshot({ path: `${OUT}/desk-agents-${w}.png` });
      await page.getByText("Revenue ops").evaluate((el) => el.scrollIntoView({ block: "center" }));
      await page.waitForTimeout(400);
      await page.screenshot({ path: `${OUT}/desk-agents-${w}-end.png` });
    });
  });
}
