import { test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.use({ launchOptions: { executablePath: "/opt/pw-browsers/chromium" } });

const OUT = process.env.SHOT_DIR ?? "shots";

// 390x500 stands in for a 390x844 phone with the keyboard up (the field
// autofocuses, so the keyboard is up the moment the page opens).
for (const [w, h] of [
  [390, 844],
  [390, 500],
  [1440, 900],
] as const) {
  test.describe(`${w}x${h}`, () => {
    test.use({ viewport: { width: w, height: h } });
    test(`new agent ${w}x${h}`, async ({ page }) => {
      mockLangGraphAPI(page, { threads: [] });
      await page.route("**/api/agents/check?*", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ available: false, name: "seo-auditor" }),
        }),
      );
      await page.goto("/workspace/agents/new");
      await page.getByRole("textbox").first().waitFor();
      await page.waitForTimeout(800);
      const facts = await page.evaluate(() => {
        const box = (el: Element | null) => {
          const r = el?.getBoundingClientRect();
          return r ? [Math.round(r.top), Math.round(r.bottom)] : null;
        };
        return {
          overflow: document.documentElement.scrollWidth - window.innerWidth,
          field: box(document.querySelector("input")),
          continue: box(
            [...document.querySelectorAll("button")].find(
              (b) => b.textContent?.trim() === "Continue",
            ) ?? null,
          ),
        };
      });
      console.log(`${w}x${h} ${JSON.stringify(facts)}`);
      const tag = h === 500 ? "keyboard-390" : `${w}`;
      await page.screenshot({ path: `${OUT}/name-${tag}.png` });
      if (h === 500) return;
      await page.getByRole("textbox").first().fill("seo-auditor");
      await page.getByRole("button", { name: "Continue" }).click();
      await page.getByRole("alert").first().waitFor();
      await page.waitForTimeout(300);
      await page.screenshot({ path: `${OUT}/name-error-${w}.png` });
    });
  });
}
