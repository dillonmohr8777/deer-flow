import { test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.use({
  launchOptions: { executablePath: "/opt/pw-browsers/chromium" },
  serviceWorkers: "block",
});

const OUT = process.env.SHOT_DIR ?? "shots";
const min = 60_000;
const ago = (m: number) => new Date(Date.now() - m * min).toISOString();

const SESSIONS = [
  {
    id: "s-run",
    title: "Omega Landscape spring SEO audit, top 20 service pages",
    status: "in_progress",
    created_at: ago(14),
    updated_at: ago(1),
    last_error: null,
  },
  {
    id: "s-done",
    title: "Draft three Meta ad variants for the KJB trunk show",
    status: "completed",
    created_at: ago(60 * 26),
    updated_at: ago(60 * 25),
    last_error: null,
  },
  {
    id: "s-lost",
    title: "Competitor pricing table for Pro Fence & Deck",
    status: "unknown",
    created_at: ago(60 * 50),
    updated_at: ago(60 * 49),
    last_error: "provider_outcome_unknown",
  },
];

const DETAIL = {
  ...SESSIONS[0],
  operation_pending: false,
  history_truncated: false,
  turn: { id: "t1", status: "in_progress", output_verified: false },
  items: [
    {
      id: "i1",
      type: "message",
      turn_id: "t1",
      subagent_id: null,
      role: "user",
      text: "Audit the top 20 service pages on omegalandscape.example for title, meta description and internal links. Done means a table with one row per page and the three fixes that matter most.",
      status: "completed",
    },
    {
      id: "i2",
      type: "create_subagent_call",
      turn_id: "t1",
      subagent_id: "sa_1",
      role: null,
      text: "Crawl the 20 service pages and record title, meta description and internal link count for each.",
      status: "completed",
    },
    {
      id: "i3",
      type: "agent_message",
      turn_id: "t1",
      subagent_id: "sa_1",
      phase: "final_answer",
      sender_agent_id: "sa_1",
      recipient_agent_id: "root",
      role: "assistant",
      text: "Crawled 20 of 20 pages. 7 titles are over 60 characters, 4 pages have no meta description, and 3 pages have no internal links in.",
      status: "completed",
    },
    {
      id: "i4",
      type: "message",
      turn_id: "t1",
      subagent_id: null,
      role: "assistant",
      text: "Writing the table now. The three fixes that matter most so far: meta descriptions on the four lawn-care pages, shorter titles on the hardscape pages, and links into the three orphan pages from the services hub.",
      status: "in_progress",
    },
  ],
  artifacts: [
    {
      id: "a1",
      path: "outputs/omega-seo-audit.csv",
      turn_id: "t1",
      content_url: "",
    },
  ],
  required_actions: [],
  usage: { input_tokens: 18_204, output_tokens: null },
};

async function setup(
  page: Page,
  mode: "ok" | "unavailable" | "error" | "empty",
) {
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/openai-agents/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (mode === "error" && path.endsWith("/status"))
      return route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "openai_agents_unavailable" }),
      });
    let body: unknown;
    if (path.endsWith("/status"))
      body = {
        owner_scope: "scope-one",
        configured: mode !== "unavailable",
        available: mode !== "unavailable",
        sdk_version: "1.0",
        model: "gpt-6.1-sol",
        max_concurrent_subagents: 3,
        browser_available: false,
        reason: mode === "unavailable" ? "missing_api_key" : null,
      };
    else if (path.endsWith("/sessions"))
      body = { data: mode === "ok" ? SESSIONS : [] };
    else body = DETAIL;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
}

for (const [w, h] of [
  [390, 844],
  [1440, 900],
] as const) {
  test.describe(`${w}x${h}`, () => {
    test.use({ viewport: { width: w, height: h } });
    test(`openai ${w}`, async ({ page }) => {
      await setup(page, "ok");
      await page.goto("/workspace/openai");
      await page.getByText("Draft three Meta ad").waitFor();
      await page.waitForTimeout(500);
      await page.screenshot({ path: `${OUT}/openai-${w}.png` });
      await page.getByText("Omega Landscape spring SEO audit").first().click();
      await page.getByText("Writing the table now").waitFor();
      await page.waitForTimeout(500);
      await page.screenshot({ path: `${OUT}/openai-session-${w}.png` });
    });
    for (const mode of ["unavailable", "error", "empty"] as const)
      test(`openai ${mode} ${w}`, async ({ page }) => {
        await setup(page, mode);
        await page.goto("/workspace/openai");
        await page.waitForTimeout(2500);
        await page.screenshot({ path: `${OUT}/openai-${mode}-${w}.png` });
      });
  });
}
