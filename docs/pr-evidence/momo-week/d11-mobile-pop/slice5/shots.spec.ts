import { test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.use({ launchOptions: { executablePath: "/opt/pw-browsers/chromium" } });

const OUT = process.env.SHOT_DIR ?? "shots";
const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";

// A realistic roster: canon specialists with Momo art, plus one custom
// agent that has none (it keeps the ink monogram).
const AGENTS = [
  { name: "dillon-growth", description: "Plans paid and organic growth for each client and drafts the monthly growth memo.", model: "claude-sonnet", tool_groups: ["web", "file:read"], skills: ["seo-audit"] },
  { name: "dillon-revenue", description: "Reconciles invoices against collected revenue and flags accounts that slip.", model: "claude-sonnet", tool_groups: ["file:read"], skills: [] },
  { name: "momentum-independent-verifier", description: "Checks another agent's finished work against the brief before it ships.", model: "claude-sonnet", tool_groups: [], skills: [] },
  { name: "dillon-intelligence", description: "Researches prospects and competitors and cites every source.", model: "claude-sonnet", tool_groups: ["web"], skills: [] },
  { name: "fagan-onboarding", description: "Walks a new client through their first week.", model: "claude-sonnet", tool_groups: [], skills: [] },
];

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
    test(`agents ${w}`, async ({ page }) => {
      mockLangGraphAPI(page, { agents: AGENTS });
      await page.goto("/workspace/agents");
      await page.getByRole("heading", { name: "Agents", level: 1 }).waitFor();
      await page.getByRole("heading", { level: 2 }).first().waitFor();
      await page.waitForTimeout(1200);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      const chat = await page.getByRole("button", { name: /^Chat/ }).first().boundingBox();
      console.log(`agents ${w} overflow=${overflow} chat=${Math.round(chat!.width)}x${Math.round(chat!.height)}`);
      await page.screenshot({ path: `${OUT}/agents-${w}.png` });
      if (mobile) {
        await page.evaluate(() => document.querySelector("ul")?.lastElementChild?.scrollIntoView({ block: "end" }));
        await page.waitForTimeout(200);
        await page.screenshot({ path: `${OUT}/agents-${w}-2.png` });
      }
    });
  });
}
