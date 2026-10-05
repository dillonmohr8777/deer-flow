import { test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.use({ launchOptions: { executablePath: "/opt/pw-browsers/chromium" } });

const OUT = process.env.SHOT_DIR ?? "shots";

const day = 86_400_000;
const ago = (days: number) => new Date(Date.now() - days * day).toISOString();

// Trash with four documents: one from a live project, one whose project was
// deleted (restore opens the project picker), one nearly expired and one
// with a long name.
for (const [w, h] of [
  [390, 844],
  [1440, 900],
] as const) {
  test.describe(`${w}x${h}`, () => {
    test.use({ viewport: { width: w, height: h } });
    test(`trash ${w}x${h}`, async ({ page }) => {
      mockLangGraphAPI(page, {
        threads: [],
        projects: [
          { id: "p-acme", name: "Acme spring launch" },
          { id: "p-omega", name: "Omega Landscape audit" },
        ],
        trashDocuments: [
          {
            id: "d1",
            project_id: "p-acme",
            name: "launch-brief-v3.docx",
            size_bytes: 48_213,
            trashed_at: ago(2),
            trash_origin: {
              project_id: "p-acme",
              project_name: "Acme spring launch",
            },
          },
          {
            id: "d2",
            project_id: "p-gone",
            name: "keyword-gap-analysis-q3-final-reviewed-by-client.xlsx",
            size_bytes: 1_204_331,
            trashed_at: ago(12),
            trash_origin: {
              project_id: "p-gone",
              project_name: "Pritzker Law retainer",
            },
          },
          {
            id: "d3",
            project_id: "p-omega",
            name: "site-crawl.csv",
            size_bytes: 920_114,
            trashed_at: ago(29.6),
            trash_origin: {
              project_id: "p-omega",
              project_name: "Omega Landscape audit",
            },
          },
          {
            id: "d4",
            project_id: "p-x",
            name: "notes.md",
            size_bytes: 2_048,
            trashed_at: ago(5),
            trash_origin: null,
          },
        ],
      });
      await page.goto("/workspace/trash");
      await page.getByText("launch-brief-v3.docx").waitFor();
      await page.waitForTimeout(400);
      await page.screenshot({ path: `${OUT}/trash-${w}.png` });
      await page
        .getByRole("listitem")
        .filter({ hasText: "keyword-gap" })
        .getByRole("button", { name: /Restore/ })
        .click();
      await page.getByRole("dialog").waitFor();
      await page.waitForTimeout(400);
      await page.screenshot({ path: `${OUT}/trash-picker-${w}.png` });
    });
    test(`trash empty ${w}x${h}`, async ({ page }) => {
      mockLangGraphAPI(page, { threads: [] });
      await page.goto("/workspace/trash");
      await page.getByText("Trash is empty.").waitFor();
      await page.waitForTimeout(400);
      await page.screenshot({ path: `${OUT}/trash-empty-${w}.png` });
    });
  });
}
