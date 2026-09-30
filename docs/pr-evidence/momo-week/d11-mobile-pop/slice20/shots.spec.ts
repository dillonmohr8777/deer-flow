import { test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.use({ launchOptions: { executablePath: "/opt/pw-browsers/chromium" } });

// Slice 20 evidence: the Workflow room on the paper page frame.
// Run from frontend/ with this file copied into tests/e2e and SHOT_DIR set.
const OUT = process.env.SHOT_DIR ?? "shots";
const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";
const schema = {
  type: "object",
  properties: { brief: { type: "string", title: "Task brief", minLength: 1, maxLength: 1000 } },
  required: ["brief"],
  additionalProperties: false,
};
const def = (id: string, title: string, category: string, summary: string) => ({
  id,
  title,
  category,
  summary,
  input_schema: schema,
  output_schema: { type: "object", properties: { result: { type: "string" } } },
  steps: ["Plan", "Draft", "Review"],
  acceptance: ["Cites every source it uses", "Names what it could not verify"],
  example_inputs: { brief: "Sample brief" },
  requires_browser: false,
});
const CATALOG = [
  def("seo-audit", "Local SEO audit", "SEO", "Checks a client's service pages against their map pack rivals and drafts fixes."),
  def("monthly-report", "Monthly performance recap", "Reporting", "Drafts the month's results with each number traced to its source."),
  def("ad-copy", "Paid search ad variants", "Paid media", "Writes six headline and description sets inside the brand voice."),
  def("site-qa", "Pre-launch site QA", "Web", "Walks the forms, redirects and mobile layout before a site goes live."),
  def("review-replies", "Review reply drafts", "Reputation", "Drafts replies to new Google reviews for the owner to approve."),
];
const STATUS = {
  owner_scope: "scope-one",
  enabled: true,
  frameworks: {
    langgraph: { available: true, detail: "Shared native graph" },
    crewai: { available: false, detail: "Isolated worker not configured" },
  },
  limits: {
    max_running: 3,
    max_queued: 100,
    max_model_calls_per_run: 6,
    max_output_tokens_per_run: 8192,
    max_browser_sessions_per_owner: 1,
  },
  running: 1,
  queued: 0,
};
const now = Date.now();
const run = (id: string, title: string, status: string, minsAgo: number, accepted = false, error: string | null = null) => ({
  id,
  workflow_id: "seo-audit",
  title,
  framework: "langgraph",
  status,
  accepted,
  created_at: new Date(now - minsAgo * 60_000).toISOString(),
  updated_at: new Date(now - minsAgo * 60_000 + 90_000).toISOString(),
  steps: [],
  output: null,
  evidence: [],
  usage: { model_calls: 2, input_tokens: 800, output_tokens: 300, cost: null },
  error,
  artifact: null,
});
const RUNS = [
  run("r1", "Local SEO audit: Acme Landscaping", "running", 3),
  run("r2", "Monthly performance recap: Omega", "completed", 95, true),
  run("r3", "Pre-launch site QA: Fresh Blends", "failed", 60 * 26, false, "Model-call budget reached before review"),
];

for (const [w, h, mobile] of [[390, 844, true], [430, 932, true], [1440, 900, false]] as const) {
  test.describe(`${w}`, () => {
    test.use({ viewport: { width: w, height: h }, ...(mobile ? { userAgent: IPHONE, isMobile: true, hasTouch: true } : {}) });
    for (const slug of ["room", "error"] as const) {
      test(`${slug} ${w}`, async ({ page }) => {
        mockLangGraphAPI(page);
        await page.route(/\/api\/workflows\//, (route) => {
          const url = route.request().url();
          const json = (body: unknown, status = 200) =>
            route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
          if (slug === "error") return json({}, 503);
          if (url.endsWith("/status")) return json(STATUS);
          if (url.endsWith("/catalog")) return json({ workflows: CATALOG, total: CATALOG.length });
          if (url.endsWith("/runs")) return json({ runs: RUNS });
          return json(RUNS[0]);
        });
        await page.goto(`/workspace/workflows`);
        await page.getByRole("heading", { level: 1 }).waitFor();
        await page.waitForTimeout(1800);
        await page.screenshot({ path: `${OUT}/${slug}-${w}.png` });
        if (slug === "room") {
          // The page scrolls in its body, so bring the catalog up and pick one.
          await page.locator("#workflow-catalog").scrollIntoViewIfNeeded();
          await page.waitForTimeout(300);
          await page.screenshot({ path: `${OUT}/catalog-${w}.png` });
          await page.getByRole("button", { name: /^Local SEO audit SEO/ }).click();
          await page.waitForTimeout(500);
          await page.getByRole("button", { name: /^Local SEO audit: Acme/ }).click();
          await page.waitForTimeout(800);
          await page.screenshot({ path: `${OUT}/run-open-${w}.png` });
        }
        const facts = await page.evaluate(() => {
          const box = (el: Element | null) => {
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return `${Math.round(r.left)},${Math.round(r.top)} ${Math.round(r.width)}x${Math.round(r.height)}`;
          };
          const h1 = document.querySelector("h1");
          return {
            overflow: document.documentElement.scrollWidth - window.innerWidth,
            docScroll: document.documentElement.scrollHeight - window.innerHeight,
            h1: box(h1),
            h1Font: h1 ? getComputedStyle(h1).fontFamily.split(",")[0] : null,
            alert: document.querySelector("[role=alert]")?.textContent ?? null,
          };
        });
        console.log(`FACTS ${slug} ${w} ${JSON.stringify(facts)}`);
      });
    }
  });
}
