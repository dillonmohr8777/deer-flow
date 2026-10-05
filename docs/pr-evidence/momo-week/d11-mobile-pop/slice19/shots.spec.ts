import { test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.use({ launchOptions: { executablePath: "/opt/pw-browsers/chromium" } });

// Slice 19 evidence: a project's header on the shared page-header pattern.
// Run from frontend/ with this file copied into tests/e2e and SHOT_DIR set.
const OUT = process.env.SHOT_DIR ?? "shots";
const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";
const P = "11111111-1111-4111-8111-111111111111";
const A = "22222222-2222-4222-8222-222222222222";
const today = new Date();
today.setHours(0, 40, 0, 0);
const THREADS = [
  "Draft the September SEO report for the Bucks County service pages",
  "Fix the broken contact form redirect on mobile Safari",
  "Summarize last week's call notes",
].map((title, i) => ({
  thread_id: `t${i}`,
  title,
  updated_at: new Date(today.getTime() - i * 86_400_000).toISOString(),
  metadata: { deerflow_project_id: P },
}));
const PROJECTS = [
  {
    id: P,
    name: "Acme Landscaping retainer",
    instructions:
      "Monthly SEO and paid search for Acme's Bucks County service pages. Write for homeowners, lead with the free estimate.\n\nNever quote prices.",
  },
  { id: A, name: "Spring 2025 cleanup campaign", status: "archived" as const },
];

for (const [w, h, mobile] of [[390, 844, true], [430, 932, true], [1440, 900, false]] as const) {
  test.describe(`${w}`, () => {
    test.use({ viewport: { width: w, height: h }, ...(mobile ? { userAgent: IPHONE, isMobile: true, hasTouch: true } : {}) });
    for (const [slug, id] of [["project", P], ["project-archived", A]] as const) {
      test(`${slug} ${w}`, async ({ page }) => {
        mockLangGraphAPI(page, { projects: PROJECTS as never, threads: THREADS as never });
        await page.goto(`/workspace/projects/${id}`);
        await page.getByRole("heading", { level: 1 }).waitFor();
        await page.getByRole("tab", { name: "Chats" }).waitFor();
        await page.waitForTimeout(1500);
        await page.screenshot({ path: `${OUT}/${slug}-${w}.png` });
        const facts = await page.evaluate(() => {
          const box = (el: Element | null) => {
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return `${Math.round(r.left)},${Math.round(r.top)} ${Math.round(r.width)}x${Math.round(r.height)}`;
          };
          return {
            overflow: document.documentElement.scrollWidth - window.innerWidth,
            h1: box(document.querySelector("main h1, h1")),
            newChat: box(document.querySelector("a[href^='/workspace/chats/new?project']")),
            tabs: box(document.querySelector("[role='tablist']")),
            firstChat: box(document.querySelector("a[href^='/workspace/chats/t0']")),
          };
        });
        console.log(`FACTS ${slug} ${w} ${JSON.stringify(facts)}`);
      });
    }
  });
}
