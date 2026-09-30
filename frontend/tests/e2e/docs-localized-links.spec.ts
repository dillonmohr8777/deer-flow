import { expect, test, type Page } from "@playwright/test";

async function expectRetiredDocsRoute(page: Page, entryURL: string) {
  const response = await page.request.get(entryURL, { maxRedirects: 0 });
  expect(response.status()).toBe(307);
  expect(response.headers().location).toBe("/");

  await page.goto(entryURL);
  await expect(page).toHaveURL(new URL("/", page.url()).href);
  await expect(
    page.getByRole("heading", { name: "Say hello to MomoBot", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Enter the workspace", exact: true }),
  ).toHaveAttribute("href", "/workspace");
  await expect(page.locator("a.nextra-card")).toHaveCount(0);
  await expect(
    page.locator('a[href^="/en/docs"], a[href^="/zh/docs"]'),
  ).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: "Question? Give us feedback", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: "Edit this page", exact: true }),
  ).toHaveCount(0);
}

test.describe("Retired upstream documentation routes", () => {
  test("redirects the former English card entry to MomoBot", async ({
    page,
  }) => {
    await expectRetiredDocsRoute(page, "/en/docs/introduction/core-concepts");
    await expectRetiredDocsRoute(page, "/en/docs/introduction/why-deerflow");
  });

  test("redirects the former Chinese card entry to MomoBot", async ({
    page,
  }) => {
    await expectRetiredDocsRoute(page, "/zh/docs/introduction/core-concepts");
    await expectRetiredDocsRoute(page, "/zh/docs/introduction/harness-vs-app");
  });

  test("redirects the former English Markdown entry to MomoBot", async ({
    page,
  }) => {
    await expectRetiredDocsRoute(page, "/en/docs/application/workspace-usage");
    await expectRetiredDocsRoute(
      page,
      "/en/docs/application/agents-and-threads",
    );
  });

  test("redirects the former Chinese Markdown entries to MomoBot", async ({
    page,
  }) => {
    await expectRetiredDocsRoute(page, "/zh/docs/application/quick-start");
    await expectRetiredDocsRoute(page, "/zh/docs/application/configuration");
  });

  test("redirects the retired docs root without upstream navigation", async ({
    page,
  }) => {
    await expectRetiredDocsRoute(page, "/en/docs");
  });

  test("redirects retired feedback and edit pages to the branded landing", async ({
    page,
  }) => {
    await expectRetiredDocsRoute(page, "/en/docs/application/quick-start");
  });
});
