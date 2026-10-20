import { readFileSync, existsSync } from "node:fs";
import { extname, join, normalize } from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

/**
 * MomoBot About + Agents lineup against the mocked gateway.
 *
 * By default the kit is synthetic (fake agents, a 1x1 svg). Set
 * LINEUP_KIT_DIR to a staged content dir to render the real kit from disk
 * (nothing from it is committed) and LINEUP_SHOTS_DIR to save screenshots.
 */
const KIT_DIR = process.env.LINEUP_KIT_DIR;
const SHOTS_DIR = process.env.LINEUP_SHOTS_DIR;

const SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><rect width="1" height="1" fill="#1b4b9e"/></svg>';

const FAKE_KIT = {
  name: "Fake kit",
  show_pricing: false,
  brand: { end_card_line: "Fake end card." },
  max_plus: {
    id: "fake-max",
    name: "Fake Max",
    job: "Fake job.",
    tagline: "Fake Max. All fake agents.",
    bundle_line: "Or get them all in one, fake.",
    color: "#1b4b9e",
    icon: "icons/fake.svg",
    includes: [],
  },
  agents: Array.from({ length: 5 }, (_, i) => ({
    id: `fake-${i + 1}`,
    order: i + 1,
    name: `Fake Agent ${i + 1}`,
    short_name: `F${i + 1}`,
    job: `Does fake job number ${i + 1} for the fake team.`,
    color: "#1b4b9e",
    icon: "icons/fake.svg",
    icon_alt: `Fake icon ${i + 1}`,
  })),
  videos: {},
};
const FAKE_ABOUT =
  "**Fake lead.** Fake paragraph.\n\n**Steps.**\n1. One\n2. Two";

async function mockBrand(page: Page) {
  mockLangGraphAPI(page, { scheduledTasks: [] });
  await page.route("**/api/momobot-brand/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(
      "/api/momobot-brand/",
      "",
    );
    if (path === "kit" || path === "about") {
      if (KIT_DIR) {
        const kit = JSON.parse(
          readFileSync(join(KIT_DIR, "agents.json"), "utf-8"),
        ) as Record<string, unknown>;
        if (path === "kit") {
          // Mirror the server: no price data while show_pricing is false.
          return route.fulfill({
            json: JSON.parse(
              JSON.stringify(kit, (k, v) => (k === "price" ? undefined : v)),
            ),
          });
        }
        const md = readFileSync(join(KIT_DIR, "about.md"), "utf-8")
          .split("\n\n")
          .filter((b) => !b.includes("<!--pricing-->"))
          .join("\n\n");
        return route.fulfill({ json: { markdown: md, show_pricing: false } });
      }
      return route.fulfill({
        json:
          path === "kit"
            ? FAKE_KIT
            : { markdown: FAKE_ABOUT, show_pricing: false },
      });
    }
    const file = normalize(path.replace("assets/", ""));
    if (KIT_DIR && !file.startsWith("..") && existsSync(join(KIT_DIR, file))) {
      return route.fulfill({
        body: readFileSync(join(KIT_DIR, file)),
        contentType:
          { ".svg": "image/svg+xml", ".png": "image/png", ".mp4": "video/mp4" }[
            extname(file)
          ] ?? "application/octet-stream",
      });
    }
    return route.fulfill({ body: SVG, contentType: "image/svg+xml" });
  });
}

for (const [name, width, height] of [
  ["390", 390, 844],
  ["768", 768, 1024],
  ["1440", 1440, 900],
] as const) {
  test.describe(`viewport ${name}`, () => {
    test.use({ viewport: { width, height } });

    test("lineup has no horizontal overflow and shows prices nowhere", async ({
      page,
    }) => {
      await mockBrand(page);
      await page.goto("/workspace/lineup");
      await expect(
        page.getByRole("heading", { name: "MomoBot Agents", level: 1 }),
      ).toBeVisible();
      await page.waitForLoadState("networkidle");
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
      expect(await page.locator("body").innerText()).not.toMatch(/\$\d/);
      if (SHOTS_DIR) {
        await page.screenshot({
          path: join(SHOTS_DIR, `lineup-${name}.png`),
        });
        await page
          .getByRole("list", { name: "Agents" })
          .scrollIntoViewIfNeeded();
        await page.mouse.wheel(0, 400);
        await page.screenshot({
          path: join(SHOTS_DIR, `lineup-${name}-roll.png`),
        });
      }
    });

    test("about renders the copy", async ({ page }) => {
      await mockBrand(page);
      await page.goto("/workspace/about");
      await expect(
        page.getByRole("heading", { name: "About MomoBot", level: 1 }),
      ).toBeVisible();
      expect(await page.locator("body").innerText()).not.toMatch(/\$\d/);
      if (SHOTS_DIR) {
        await page.screenshot({
          path: join(SHOTS_DIR, `about-${name}.png`),
        });
      }
    });
  });
}
