import { test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.use({ launchOptions: { executablePath: "/opt/pw-browsers/chromium" } });

// Slice 21 evidence: a workflow run's receipt (detail sheet).
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
const iso = (minsAgo: number) => new Date(now - minsAgo * 60_000).toISOString();
// The step journal as workflow_service records it: each step logs
// running, then completed, with snake_case detail codes.
const JOURNAL = [
  { name: "validate", status: "completed", detail: "input_schema_validated" },
  { name: "research", status: "completed", detail: "not_required" },
  { name: "plan", status: "running", worker_id: "wf_3f9a1c0d2e4b5a6978c1d2e3f4a5b6c7", model: "gpt-6.1-sol", effort: "low" },
  { name: "plan", status: "completed", worker_id: "wf_3f9a1c0d2e4b5a6978c1d2e3f4a5b6c7", model: "gpt-6.1-sol", effort: "low" },
  { name: "draft", status: "running", worker_id: "wf_8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e", model: "gpt-6.1-sol", effort: "medium" },
  { name: "draft", status: "completed", worker_id: "wf_8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e", model: "gpt-6.1-sol", effort: "medium" },
  { name: "verify", status: "running", worker_id: "wf_1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d", model: "gpt-6.1-sol", effort: "medium" },
  { name: "verify", status: "completed", worker_id: "wf_1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d", model: "gpt-6.1-sol", effort: "medium" },
  { name: "accept", status: "completed", detail: "schema_and_independent_review_passed" },
];
const base = {
  workflow_id: "seo-audit",
  framework: "langgraph",
  steps: [] as unknown[],
  output: null as unknown,
  evidence: [] as unknown[],
  usage: { model_calls: 3, input_tokens: 18420, output_tokens: 2310, cost: null },
  error: null as string | null,
  artifact: null as unknown,
  accepted: false,
};
const RUNS = [
  { ...base, id: "7c1e9a52-4b0f-4d7e-9a31-5f2c8e6d1b04", title: "Local SEO audit: Acme Landscaping", status: "running", created_at: iso(3), updated_at: iso(2), steps: JOURNAL.slice(0, 5), usage: { ...base.usage, model_calls: 1, input_tokens: 5210, output_tokens: 640 } },
  {
    ...base,
    id: "b2d4f6a8-1c3e-4a5b-8d7f-0e2c4a6b8d1f",
    title: "Monthly performance recap: Omega",
    status: "completed",
    accepted: true,
    created_at: iso(95),
    updated_at: iso(92),
    steps: JOURNAL,
    output: {
      headline: "Leads up 18% on August, driven by the spring cleanup landing page.",
      summary: "Form fills rose from 41 to 48 (input:ga4_export). Calls held at 22. Cost per lead fell to $38. Search impressions for 'landscaper near me' are unknown: the Search Console export was not supplied.",
      next_steps: ["Move $300 from Display to Search", "Refresh the cleanup page hero before October"],
    },
    evidence: [{ kind: "input", reference: "input:ga4_export" }, { kind: "browserbase", reference: "/api/browserbase/research/rs_91", bytes: 48213, sha256: "9f2c1e7a4b3d5c6e8f0a1b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3e4f5a6" }],
    artifact: { bytes: 2204, sha256: "a".repeat(64) },
  },
  { ...base, id: "e5f6a7b8-9c0d-4e1f-a2b3-c4d5e6f7a8b9", title: "Pre-launch site QA: Fresh Blends", status: "failed", created_at: iso(60 * 26), updated_at: iso(60 * 26 - 4), steps: JOURNAL.slice(0, 7), error: "run_model_budget_exhausted", usage: { ...base.usage, model_calls: 6 } },
];

for (const [w, h, mobile] of [[390, 844, true], [1440, 900, false]] as const) {
  test.describe(`${w}`, () => {
    test.use({ viewport: { width: w, height: h }, ...(mobile ? { userAgent: IPHONE, isMobile: true, hasTouch: true } : {}) });
    for (const [slug, index] of [["accepted", 1], ["running", 0], ["failed", 2]] as const) {
      test(`${slug} ${w}`, async ({ page }) => {
        mockLangGraphAPI(page);
        await page.route(/\/api\/workflows\//, (route) => {
          const url = route.request().url();
          const json = (body: unknown) =>
            route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
          if (url.endsWith("/status")) return json(STATUS);
          if (url.endsWith("/catalog")) return json({ workflows: CATALOG, total: CATALOG.length });
          if (url.endsWith("/runs")) return json({ runs: RUNS });
          const run = RUNS.find((r) => url.includes(r.id));
          return json(run ?? RUNS[0]);
        });
        await page.goto(`/workspace/workflows`);
        await page.getByRole("heading", { level: 1 }).waitFor();
        await page.getByRole("button", { name: new RegExp(`^${RUNS[index]!.title}`) }).click();
        const sheet = page.locator("section[aria-label='Workflow run']");
        await sheet.waitFor();
        await page.waitForTimeout(600);
        await sheet.evaluate((el) => el.scrollIntoView({ block: "start" }));
        await page.waitForTimeout(300);
        await page.screenshot({ path: `${OUT}/${slug}-${w}.png` });
        if (slug === "accepted") {
          await sheet.evaluate((el) => el.scrollIntoView({ block: "end" }));
          await page.waitForTimeout(300);
          await page.screenshot({ path: `${OUT}/${slug}-${w}-end.png` });
          const box = await sheet.boundingBox();
          await page.setViewportSize({ width: w, height: Math.ceil((box?.height ?? h) + 200) });
          await sheet.evaluate((el) => el.scrollIntoView({ block: "start" }));
          await page.waitForTimeout(300);
          await sheet.screenshot({ path: `${OUT}/${slug}-${w}-sheet.png` });
        }
        const facts = await page.evaluate(() => ({
          overflow: document.documentElement.scrollWidth - window.innerWidth,
          sheetH: Math.round(document.querySelector("section[aria-label='Workflow run']")!.getBoundingClientRect().height),
          small: [...document.querySelectorAll("section[aria-label='Workflow run'] :is(button,a)")]
            .map((el) => el.getBoundingClientRect())
            .filter((r) => r.height > 0 && r.height < 44).length,
        }));
        console.log(`FACTS ${slug} ${w} ${JSON.stringify(facts)}`);
      });
    }
  });
}
