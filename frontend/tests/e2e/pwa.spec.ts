import { expect, test } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

// Dedicated worker tests opt in; API fixture suites keep workers blocked.
test.use({ serviceWorkers: "allow" });

const IPHONE_USER_AGENT =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 Version/26.0 Mobile/15E148 Safari/604.1";
const PUBLIC_PATHS = [
  "/offline.html",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/icon-512-maskable.png",
  "/icons/apple-touch-icon.png",
].sort();

test("publishes iPhone standalone metadata and registers the public-only worker", async ({
  page,
  request,
}) => {
  const manifestResponse = await request.get("/manifest.webmanifest");
  expect(manifestResponse.ok()).toBe(true);
  const manifest = await manifestResponse.json();
  expect(manifest).toMatchObject({
    id: "/workspace",
    start_url: "/workspace",
    scope: "/",
    display: "standalone",
  });
  expect(manifest.icons.map((icon: { src: string }) => icon.src)).toContain(
    "/icons/icon-512-maskable.png",
  );
  await page.goto("/");
  await expect(page.locator('link[rel="manifest"]')).toHaveAttribute(
    "href",
    "/manifest.webmanifest",
  );
  await expect(
    page.locator('meta[name="mobile-web-app-capable"]'),
  ).toHaveAttribute("content", "yes");
  await expect(
    page.locator('meta[name="apple-mobile-web-app-title"]'),
  ).toHaveAttribute("content", "MomoBot");
  await expect(page.locator('meta[name="viewport"]')).toHaveAttribute(
    "content",
    /viewport-fit=cover/,
  );
  await expect
    .poll(async () =>
      page.evaluate(async () => {
        const registration = await navigator.serviceWorker.getRegistration("/");
        return registration?.active?.scriptURL.endsWith("/sw.js") ?? false;
      }),
    )
    .toBe(true);
  const worker = await request.get("/sw.js");
  expect(worker.headers()["content-type"]).toContain("javascript");
  expect(worker.headers()["cache-control"]).toContain("no-store");
});

for (const width of [390, 768, 1440]) {
  test(`iPhone install help fits ${width}px with 44px controls and reduced motion`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.addInitScript((userAgent) => {
      Object.defineProperty(navigator, "userAgent", { get: () => userAgent });
      Object.defineProperty(navigator, "standalone", { get: () => false });
    }, IPHONE_USER_AGENT);
    await page.goto("/");
    const trigger = page.getByRole("button", {
      name: "Install MomoBot",
      exact: true,
    });
    await expect(trigger).toBeVisible();
    const triggerBounds = await trigger.boundingBox();
    expect(triggerBounds?.height).toBeGreaterThanOrEqual(44);
    await trigger.click();
    const dialog = page.getByRole("dialog", {
      name: "Keep MomoBot one tap away",
    });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText(/Open as Web App/)).toBeVisible();
    for (const control of await dialog.getByRole("button").all()) {
      const bounds = await control.boundingBox();
      expect(bounds?.height).toBeGreaterThanOrEqual(44);
      expect(bounds?.width).toBeGreaterThanOrEqual(44);
    }
    expect(
      await dialog.evaluate(
        (element) => getComputedStyle(element).animationName,
      ),
    ).toBe("none");
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
    await dialog.getByRole("button", { name: "Got it" }).click();
    await expect(trigger).toBeFocused();
    await page.getByRole("button", { name: "Dismiss install help" }).click();
    await expect(trigger).toBeHidden();
    await page.reload();
    await expect(trigger).toBeHidden();
  });
}

test.describe("install help on a phone workspace", () => {
  test.use({
    serviceWorkers: "block",
    viewport: { width: 390, height: 844 },
    userAgent: IPHONE_USER_AGENT,
    isMobile: true,
    hasTouch: true,
  });

  test("docks on the tab bar and the page ends above it", async ({ page }) => {
    await page.addInitScript(() =>
      Object.defineProperty(navigator, "standalone", { get: () => false }),
    );
    mockLangGraphAPI(page);
    await page.goto("/workspace/chats/new");
    const hint = page.getByRole("complementary", {
      name: "MomoBot installation",
    });
    await expect(hint).toBeVisible();
    const strip = (await hint.boundingBox())!;
    const tabs = (await page
      .getByRole("link", { name: "Chat", exact: true })
      .boundingBox())!;
    expect(strip.width).toBe(390);
    expect(strip.y + strip.height).toBeLessThanOrEqual(tabs.y + 0.5);
    const disclaimer = (await page
      .getByText("Agents can make mistakes")
      .first()
      .boundingBox())!;
    expect(disclaimer.y + disclaimer.height).toBeLessThanOrEqual(strip.y);

    // Inside a conversation the composer owns the bottom edge.
    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(page.getByTestId("workspace-tab-bar")).toBeHidden();
    await expect(hint).toBeHidden();
  });
});

test("installed iPhone sessions do not receive an install prompt", async ({
  page,
}) => {
  await page.addInitScript((userAgent) => {
    Object.defineProperty(navigator, "userAgent", { get: () => userAgent });
    Object.defineProperty(navigator, "standalone", { get: () => true });
  }, IPHONE_USER_AGENT);
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Install MomoBot", exact: true }),
  ).toBeHidden();
});

test("offline workspace navigation is generic and private API reads fail without replay", async ({
  page,
  context,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
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
    // Whatever this endpoint returns (including 401), it must never be cached.
    await fetch("/api/v1/auth/me", { credentials: "include" }).catch(
      () => undefined,
    );
  });
  const cachedPaths = await page.evaluate(async () => {
    const names = (await caches.keys()).filter((name) =>
      name.startsWith("momobot-public-offline-"),
    );
    const paths: string[] = [];
    for (const name of names) {
      const cache = await caches.open(name);
      paths.push(
        ...(await cache.keys()).map((key) => new URL(key.url).pathname),
      );
    }
    return paths.sort();
  });
  expect(cachedPaths).toEqual(PUBLIC_PATHS);
  await context.setOffline(true);
  // Check from the app document before the offline page's restrictive CSP.
  expect(
    await page.evaluate(async () => {
      try {
        await fetch("/api/v1/auth/me");
        return false;
      } catch {
        return true;
      }
    }),
  ).toBe(true);
  await page.goto("/workspace/chats/pwa-private-check", {
    waitUntil: "domcontentloaded",
  });
  await expect(
    page.getByRole("heading", { name: "Connect to continue." }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Try again" })).toHaveAttribute(
    "href",
    "/workspace",
  );
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(await page.evaluate(() => window.innerWidth));
  expect(
    await page
      .locator("img")
      .evaluate((image) => (image as HTMLImageElement).naturalWidth),
  ).toBeGreaterThan(0);
});
