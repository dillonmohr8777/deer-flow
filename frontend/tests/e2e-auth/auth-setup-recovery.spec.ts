import { expect, test, type Page } from "@playwright/test";

const SETUP_STATUS_URL = "**/api/v1/auth/setup-status";
const SERVICE_UNAVAILABLE_TITLE = "Service temporarily unavailable";

async function mockSetupStatusRecovery(
  page: Page,
  recoveredStatus: {
    needs_setup: boolean;
    registration_enabled?: boolean;
  },
  recordWorkerRequest?: (workerOwned: boolean) => void,
) {
  let requestCount = 0;

  // Worker-owned fetches bypass page routes. Context routes see the real
  // network hop whether the public worker has claimed the page yet or not.
  await page.context().route(SETUP_STATUS_URL, (route) => {
    if (route.request().method() !== "GET") {
      return route.fallback();
    }

    requestCount += 1;
    recordWorkerRequest?.(route.request().serviceWorker() !== null);
    if (requestCount === 1) {
      return route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Gateway unavailable" }),
      });
    }

    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(recoveredStatus),
    });
  });

  return () => requestCount;
}

test.describe("auth setup-status recovery", () => {
  test.beforeEach(async ({ context }) => {
    await context.route("**/api/v1/auth/providers", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ providers: [] }),
      }),
    );
  });

  test("login restores registration after setup-status retry", async ({
    page,
  }) => {
    const getRequestCount = await mockSetupStatusRecovery(page, {
      needs_setup: false,
      registration_enabled: true,
    });

    await page.goto("/login");

    await expect(page.getByText(SERVICE_UNAVAILABLE_TITLE)).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign in" })).toBeEnabled();
    await expect(
      page.getByRole("button", { name: /Don't have an account/i }),
    ).toHaveCount(0);
    expect(getRequestCount()).toBe(1);

    await page.getByRole("button", { name: "Try again" }).click();

    await expect
      .poll(getRequestCount, { message: "setup-status should be retried" })
      .toBe(2);
    await expect(page.getByText(SERVICE_UNAVAILABLE_TITLE)).toBeHidden();
    await expect(
      page.getByRole("button", { name: /Don't have an account/i }),
    ).toBeVisible();
  });

  test("setup restores the administrator form after setup-status retry", async ({
    page,
  }) => {
    const getRequestCount = await mockSetupStatusRecovery(page, {
      needs_setup: true,
    });

    await page.goto("/setup");

    await expect(page.getByText(SERVICE_UNAVAILABLE_TITLE)).toBeVisible();
    await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
    expect(getRequestCount()).toBe(1);

    await page.getByRole("button", { name: "Try again" }).click();

    await expect
      .poll(getRequestCount, { message: "setup-status should be retried" })
      .toBe(2);
    await expect(page.getByText(SERVICE_UNAVAILABLE_TITLE)).toBeHidden();
    await expect(
      page.getByRole("button", { name: "Create Admin Account" }),
    ).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Email" })).toBeVisible();
  });
});

test.describe("auth recovery with an active public service worker", () => {
  test.use({ serviceWorkers: "allow" });

  for (const width of [1280, 390]) {
    test(`login retries setup status and restores registration through the worker at ${width}px`, async ({
      page,
      context,
    }, testInfo) => {
      await page.setViewportSize({ width, height: 844 });
      await page.emulateMedia({ reducedMotion: "reduce" });
      const pageErrors: string[] = [];
      page.on("pageerror", (error) => pageErrors.push(error.message));
      await context.route("**/api/v1/auth/providers", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ providers: [] }),
        }),
      );
      await page.goto("/");
      await page.evaluate(async () => {
        await navigator.serviceWorker.register("/sw.js", {
          scope: "/",
          updateViaCache: "none",
        });
        await navigator.serviceWorker.ready;
        if (!navigator.serviceWorker.controller) {
          await new Promise<void>((resolve) =>
            navigator.serviceWorker.addEventListener(
              "controllerchange",
              () => resolve(),
              { once: true },
            ),
          );
        }
      });

      const workerRequests: boolean[] = [];
      const getRequestCount = await mockSetupStatusRecovery(
        page,
        { needs_setup: false, registration_enabled: true },
        (workerOwned) => workerRequests.push(workerOwned),
      );
      await page.goto("/login");
      await expect(page.getByText(SERVICE_UNAVAILABLE_TITLE)).toBeVisible();
      await expect(page.getByRole("button", { name: "Sign in" })).toBeEnabled();
      await expect(
        page.getByRole("button", { name: /Don't have an account/i }),
      ).toHaveCount(0);
      expect(getRequestCount()).toBe(1);

      await page.getByRole("button", { name: "Try again" }).click();
      await expect.poll(getRequestCount).toBe(2);
      await expect(page.getByText(SERVICE_UNAVAILABLE_TITLE)).toBeHidden();
      await expect(
        page.getByRole("button", { name: /Don't have an account/i }),
      ).toBeVisible();
      expect(workerRequests).toEqual([true, true]);
      expect(
        await page.evaluate(() => navigator.serviceWorker.controller !== null),
      ).toBe(true);
      await expect(page).toHaveURL(/\/login$/);
      await expect(page).toHaveTitle("MomoBot by Momentum");
      expect(pageErrors).toEqual([]);
      await page.screenshot({
        path: testInfo.outputPath(`worker-auth-recovered-${width}.png`),
      });
    });
  }
});
