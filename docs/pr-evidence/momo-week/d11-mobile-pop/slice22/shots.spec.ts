import { test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.use({ launchOptions: { executablePath: "/opt/pw-browsers/chromium" } });

// Slice 22 evidence: engine failure codes read in words, list and receipt.
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
  { ...base, id: "e5f6a7b8-9c0d-4e1f-a2b3-c4d5e6f7a8b9", title: "Pre-launch site QA: Fresh Blends", status: "failed", created_at: iso(12), updated_at: iso(9), steps: JOURNAL.slice(0, 8), error: "workflow_independent_review_rejected", usage: { ...base.usage, model_calls: 5 } },
  { ...base, id: "a1b2c3d4-5e6f-4a7b-8c9d-0e1f2a3b4c5d", title: "Local SEO audit: Acme Landscaping", status: "failed", created_at: iso(40), updated_at: iso(38), steps: JOURNAL.slice(0, 5), error: "workflow_model_call_failed", usage: { ...base.usage, model_calls: 2 } },
  { ...base, id: "f0e1d2c3-b4a5-4968-8776-655443322110", title: "Monthly performance recap: Omega", status: "failed", created_at: iso(70), updated_at: iso(69), steps: JOURNAL.slice(0, 3), error: "workflow_context_too_large", usage: { ...base.usage, model_calls: 0 } },
];

for (const [w, h, mobile] of [[390, 844, true], [1440, 900, false]] as const) {
  test.describe(`${w}`, () => {
    test.use({ viewport: { width: w, height: h }, ...(mobile ? { userAgent: IPHONE, isMobile: true, hasTouch: true } : {}) });
    test(`engine codes ${w}`, async ({ page }) => {
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
      await page.getByText("Your runs").first().waitFor();
      await page.waitForTimeout(600);
      await page.getByText("Your runs").first().evaluate((el) => el.scrollIntoView({ block: "start" }));
      await page.waitForTimeout(300);
      await page.screenshot({ path: `${OUT}/list-${w}.png` });
      await page.getByRole("button", { name: new RegExp(`^${RUNS[0]!.title}`) }).click();
      const sheet = page.locator("section[aria-label='Workflow run']");
      await sheet.waitFor();
      await page.waitForTimeout(600);
      await sheet.evaluate((el) => el.scrollIntoView({ block: "start" }));
      await page.waitForTimeout(300);
      await page.screenshot({ path: `${OUT}/detail-${w}.png` });
      const facts = await page.evaluate(() => ({
        overflow: document.documentElement.scrollWidth - window.innerWidth,
        generic: (document.body.textContent ?? "").split("could not complete this request").length - 1,
        codes: /workflow_[a-z_]+/.test(document.body.textContent ?? ""),
      }));
      console.log(`FACTS ${w} ${JSON.stringify(facts)}`);
    });
  });
}
