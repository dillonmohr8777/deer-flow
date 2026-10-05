import { test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.setTimeout(45_000);
test.use({ launchOptions: { executablePath: "/opt/pw-browsers/chromium" } });

const OUT = process.env.SHOT_DIR ?? "shots";
const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";

const routes: Record<string, string> = {
  chats: "/workspace/chats",
  new: "/workspace/chats/new",
  command: "/workspace/command-center",
  landing: "/",
};

for (const [w, h] of [
  [390, 844],
  [1440, 900],
] as const) {
  test.describe(`${w}`, () => {
    test.use({
      viewport: { width: w, height: h },
      userAgent: IPHONE,
      ...(w < 768 ? { isMobile: true, hasTouch: true } : {}),
    });
    for (const [name, path] of Object.entries(routes)) {
      test(`install-${name} ${w}`, async ({ page }) => {
        await page.addInitScript(() =>
          Object.defineProperty(navigator, "standalone", { get: () => false }),
        );
        mockLangGraphAPI(page);
        await page.goto(path);
        await page.waitForTimeout(2500);
        const hint = page.getByRole("complementary", {
          name: "MomoBot installation",
        });
        const box = (await hint.count()) ? await hint.boundingBox() : null;
        const barEl = page.locator('[data-slot="workspace-tab-bar"]');
        const bar = (await barEl.count()) ? await barEl.boundingBox() : null;
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - window.innerWidth,
        );
        console.log(
          `install-${name} ${w} hint=${JSON.stringify(box)} bar=${JSON.stringify(bar)} overflow=${overflow}`,
        );
        await page.screenshot({ path: `${OUT}/install-${name}-${w}.png` });
        if (name === "chats") {
          await page
            .getByRole("button", { name: "Install MomoBot", exact: true })
            .click();
          await page.waitForTimeout(800);
          await page.screenshot({ path: `${OUT}/install-dialog-${w}.png` });
        }
      });
    }
  });
}
