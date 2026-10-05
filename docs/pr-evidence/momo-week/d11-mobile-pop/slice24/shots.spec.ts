import { test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.setTimeout(45_000);
test.use({
  serviceWorkers: "block",
  launchOptions: { executablePath: "/opt/pw-browsers/chromium" },
});

const OUT = process.env.SHOT_DIR ?? "shots";
const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";

const ago = (minutes: number) =>
  new Date(Date.now() - minutes * 60_000).toISOString();

const SUMMARIES = [
  {
    id: "c-running",
    title: "Competitor pricing pages",
    status: "running",
    created_at: ago(2),
    updated_at: ago(1),
    last_error: null,
  },
  {
    id: "c-done",
    title: "Google Ads policy on healthcare claims",
    status: "completed",
    created_at: ago(95),
    updated_at: ago(93),
    last_error: null,
  },
  {
    id: "c-failed",
    title: "Client staging site",
    status: "failed",
    created_at: ago(60 * 26),
    updated_at: ago(60 * 26),
    last_error: "private_network_blocked",
  },
];

const DONE = {
  ...SUMMARIES[1],
  urls: ["https://support.google.com/adspolicy/answer/176031"],
  pages: [
    {
      index: 0,
      url: "https://support.google.com/adspolicy/answer/176031",
      final_url: "https://support.google.com/adspolicy/answer/176031",
      title: "Healthcare and medicines - Advertising Policies Help",
      text: "Google restricts the promotion of healthcare-related content. Some content can be advertised only if the advertiser is certified.",
      content_type: "text/html",
      screenshot_url: "/api/browserbase/research/c-done/pages/0/screenshot",
      source_mode: "public_read_only_snapshot",
    },
  ],
  session_id: "s",
  replay_url: null,
  session_closed: true,
  usage: { browser_minutes: 1, elapsed_seconds: 41, cost_usd: null },
};
const FAILED = {
  ...SUMMARIES[2],
  urls: ["https://staging.client.example/"],
  pages: [],
  session_id: null,
  replay_url: null,
  session_closed: null,
  usage: { browser_minutes: null, elapsed_seconds: 0, cost_usd: null },
};

type Scene = { runs: unknown[]; status?: number; open?: string };
const scenes: Record<string, Scene> = {
  list: { runs: SUMMARIES },
  captures: { runs: SUMMARIES, open: "Google Ads policy on healthcare claims" },
  failed: { runs: SUMMARIES, open: "Client staging site" },
  empty: { runs: [] },
  unavailable: { runs: [], status: 503 },
};

async function arrange(page: Page, scene: Scene) {
  mockLangGraphAPI(page);
  await page.route("**/api/browserbase/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/status")) {
      if (scene.status)
        return route.fulfill({
          status: scene.status,
          json: { detail: "provider_unconfigured" },
        });
      return route.fulfill({
        json: {
          owner_scope: "scope-one",
          configured: true,
          available: true,
          reason: null,
          browser_minutes: 14,
          monthly_minute_limit: 100,
          remaining_minutes: 86,
          mode: "public_read_only_snapshot",
          limits: {
            max_pages: 3,
            session_timeout_seconds: 180,
            max_sessions_per_owner: 1,
          },
        },
      });
    }
    if (path.endsWith("/research")) return route.fulfill({ json: { data: scene.runs } });
    if (path.includes("c-done")) return route.fulfill({ json: DONE });
    if (path.includes("c-failed")) return route.fulfill({ json: FAILED });
    return route.fulfill({ json: { ...DONE, ...SUMMARIES[0], pages: [] } });
  });
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
    for (const [name, scene] of Object.entries(scenes)) {
      test(`browser-${name} ${w}`, async ({ page }) => {
        await arrange(page, scene);
        await page.goto("/workspace/browser-research");
        await page.waitForTimeout(2000);
        if (scene.open) {
          await page
            .getByRole("button", { name: new RegExp(scene.open) })
            .first()
            .click();
          await page.waitForTimeout(1200);
        }
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - window.innerWidth,
        );
        console.log(`browser-${name} ${w} overflow=${overflow}`);
        await page.screenshot({ path: `${OUT}/browser-${name}-${w}.png` });
      });
    }
  });
}
