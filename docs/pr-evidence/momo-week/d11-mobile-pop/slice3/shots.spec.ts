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

const task = (id: string, title: string, h: number, err: string | null = null) => ({
  id, thread_id: null, context_mode: "fresh_thread_per_run", assistant_id: null, title, prompt: "", schedule_type: "cron",
  schedule_spec: {}, timezone: "UTC", status: "enabled", next_run_at: at(20), last_run_at: at(h), last_run_id: "r" + id,
  last_thread_id: "thread-" + id, last_error: err, run_count: 3, created_at: at(-300), updated_at: at(h),
});
const TASKS = [
  task("a", "Weekly SEO report draft for Acme Landscaping", -1),
  task("b", "Monday ad spend check", -3, "Google Ads token expired, reconnect the account"),
  task("c", "Review replies waiting in the inbox", -7),
];

async function mock(page: Page, withTasks: boolean) {
  mockLangGraphAPI(page, {
    scheduledTasks: (withTasks ? TASKS : []) as never,
    threads: (withTasks ? [{ thread_id: "thread-1", title: "Settled chat", updated_at: "2025-06-01T12:00:00Z" }] : []) as never,
    agents: [
      { name: "growth-strategist", description: "Plans growth", model: null, tool_groups: null } as never,
    ],
  });
  await page.route("**/api/features", (r) =>
    r.fulfill(json({ agents_api: { enabled: true }, desk: { enabled: true } })),
  );
  await page.route("**/api/fleet/templates", (r) => r.fulfill(json({ templates: [] })));
  await page.route("**/api/clients", (r) =>
    r.fulfill(json({ clients: [{ id: "acme", display_name: "Acme Landscaping", aliases: [], status: "active", email_domains: [], slack_channel_ids: [], registry_id: null, notes: "", created_at: at(-200), updated_at: at(-200), assignments: [], project_count: 0 }] })),
  );
  const threads = [
    { id: "t1", client_id: "acme", kind: "ticket", status: "new", subject: "Site is down after the plugin update", created_by_user_id: "c", created_at: at(-2), updated_at: at(-2) },
    { id: "t2", client_id: "acme", kind: "concern", status: "drafted", subject: "Ad spend looks high this week", created_by_user_id: "c", created_at: at(-9), updated_at: at(-5) },
    { id: "t3", client_id: "acme", kind: "post", status: "replied", subject: "Thanks for the new landing page", created_by_user_id: "c", created_at: at(-30), updated_at: at(-20) },
  ];
  await page.route("**/api/board/threads", (r) =>
    r.request().method() === "GET" ? r.fulfill(json({ threads })) : r.fallback(),
  );
}

const ROUTES = [
  ["desk-results", "/workspace/desk", true],
  ["desk-empty", "/workspace/desk", false],
  ["chats-empty", "/workspace/chats", false],
] as const;

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
    for (const [name, path, withTasks] of ROUTES) {
      test(`${name} ${w}`, async ({ page }) => {
        await mock(page, withTasks);
        await page.goto(path);
        await page.waitForLoadState("networkidle").catch(() => undefined);
        await page.waitForTimeout(2500);
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - window.innerWidth,
        );
        // Art that pokes past the content box's left edge (the phone gutter).
        const bleed = await page.evaluate(() =>
          [...document.querySelectorAll("[data-empty-state]")].map((el) => {
            const box = el.getBoundingClientRect().left;
            const art = Math.min(
              ...[...el.querySelectorAll("img")].map((i) => i.getBoundingClientRect().left),
            );
            return Math.round(box - art);
          }),
        );
        console.log(`${name} ${w} overflow=${overflow} bleed=${JSON.stringify(bleed)}`);
        await page.screenshot({ path: `${OUT}/${name}-${w}.png` });
      });
    }
  });
}
