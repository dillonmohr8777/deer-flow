import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.use({ launchOptions: { executablePath: "/opt/pw-browsers/chromium" } });

const OUT = process.env.SHOT_DIR ?? "shots";
const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";

// A realistic roster: canon specialists with Momo art, plus one custom
// agent that has none (it keeps the ink monogram).
const AGENTS = [
  { name: "dillon-brain", description: "Leads the team and hands work to the right specialist.", model: "claude-sonnet", tool_groups: [], skills: [] },
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

// Dillon Brain is a layered PaperLayers box, not a square svg: at phone size
// the box itself is 64 by round(64 * 422/480) and no layer spills out of it.
test.describe("brain 390", () => {
  test.use({ viewport: { width: 390, height: 844 }, userAgent: IPHONE, isMobile: true, hasTouch: true });
  for (const motion of ["on", "reduced"] as const) {
    test(`brain avatar ${motion}`, async ({ page }) => {
      if (motion === "on") {
        // The workspace motion switch is off by default; turn it on.
        await page.addInitScript(() => {
          const get = Storage.prototype.getItem;
          Storage.prototype.getItem = function (key: string) {
            return key.startsWith("momentum:appearance:v1:") ? JSON.stringify({ treatment: "paper", motion: true }) : get.call(this, key);
          };
        });
      } else {
        await page.emulateMedia({ reducedMotion: "reduce" });
      }
      mockLangGraphAPI(page, { agents: AGENTS });
      await page.goto("/workspace/agents");
      const root = page.locator('li:has(h2:text-is("dillon-brain")) [data-paper-layers="root"]');
      await root.waitFor();
      await page.waitForTimeout(800);
      const box = (await root.boundingBox())!;
      expect(Math.round(box.width)).toBe(64);
      expect(Math.round(box.height)).toBe(Math.round((64 * 422) / 480));
      const imgs = page.locator('li:has(h2:text-is("dillon-brain")) [data-paper-layers="root"], li:has(h2:text-is("dillon-brain")) [data-paper-layers="root"] img');
      const kind = await root.evaluate((el) => (el.tagName === "IMG" ? "flat" : "layers"));
      console.log(`brain ${motion}: ${kind} ${Math.round(box.width)}x${Math.round(box.height)}`);
      expect(kind).toBe(motion === "on" ? "layers" : "flat");
      // 1px: the top layers' own translateZ depth scales them a hair past the
      // box under perspective (0.3px at 64). The reported spill was 16x22px.
      const T = 1;
      for (const b of await imgs.evaluateAll((els) => els.map((e) => e.getBoundingClientRect().toJSON()))) {
        expect(b.left).toBeGreaterThanOrEqual(box.x - T);
        expect(b.top).toBeGreaterThanOrEqual(box.y - T);
        expect(b.right).toBeLessThanOrEqual(box.x + box.width + T);
        expect(b.bottom).toBeLessThanOrEqual(box.y + box.height + T);
      }
      await root.locator("xpath=ancestor::li").screenshot({ path: `${OUT}/brain-390-${motion}.png` });
    });
  }
});
