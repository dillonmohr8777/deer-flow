import { expect, test, type Page } from "@playwright/test";

const STASH_KEY = "momobot.invite.token";

const json = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

// An invite for an email that already has an account: sign in, then accept.
const invite = {
  email: "jesse@example.com",
  workspace_name: "Momentum",
  expires_at: "2026-10-01T00:00:00Z",
  requires_login: true,
};

async function mockInvite(page: Page, sessionEmail: string | null) {
  await page.route("**/api/v1/auth/invitations/inspect", (route) =>
    route.fulfill(json(invite)),
  );
  await page.route("**/api/v1/auth/providers", (route) =>
    route.fulfill(
      json({
        providers: [{ id: "google", display_name: "Google", type: "oidc" }],
      }),
    ),
  );
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill(
      sessionEmail
        ? json({ id: "u1", email: sessionEmail, system_role: "user" })
        : json({ detail: "Not authenticated" }, 401),
    ),
  );
}

function readStash(page: Page) {
  return page.evaluate((key) => window.sessionStorage.getItem(key), STASH_KEY);
}

test.describe("invite for an existing account", () => {
  for (const width of [390, 768, 1440]) {
    test(`signed out: offers Google and password sign-in at ${width}px`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      await mockInvite(page, null);
      await page.goto("/invite#token=e2e-invite");

      const google = page.getByRole("button", {
        name: "Continue with Google",
      });
      const passwordSignIn = page.getByRole("link", {
        name: "Sign in with password",
      });
      await expect(google).toBeVisible();
      await expect(passwordSignIn).toBeVisible();
      await expect(
        page.getByText("Sign in as jesse@example.com to accept."),
      ).toBeVisible();
      await expect(page.getByLabel(/password/i)).toHaveCount(0);
      await expect(
        page.getByRole("button", { name: "Accept invite" }),
      ).toHaveCount(0);
      await expect(passwordSignIn).toHaveAttribute(
        "href",
        "/login?next=%2Finvite",
      );
      for (const target of [google, passwordSignIn]) {
        const box = await target.boundingBox();
        expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
      }
      const overflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
      await page.screenshot({
        path: test.info().outputPath(`invite-sign-in-${width}.png`),
      });

      // Nothing waits in storage until the person leaves to sign in.
      expect(await readStash(page)).toBeNull();

      // The token is stashed right before leaving for Google, never in a URL.
      const started = page.waitForRequest(/\/api\/v1\/auth\/oauth\/google/);
      await page.route("**/api/v1/auth/oauth/google**", (route) =>
        route.fulfill({ status: 200, body: "ok" }),
      );
      await google.click();
      const request = await started;
      expect(request.url()).toContain("next=%2Finvite");
      expect(request.url()).not.toContain("e2e-invite");
      expect(JSON.parse((await readStash(page)) ?? "{}")).toMatchObject({
        token: "e2e-invite",
      });
    });
  }

  test("signed out: password sign-in stashes the token and goes to /login?next=/invite", async ({
    page,
  }) => {
    await mockInvite(page, null);
    // Stand in for the login page (registered before the visit, so a link
    // prefetch sees it too) and end the test where the link points.
    await page.route(/\/login\?/, (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "<!doctype html><title>Login</title><p>login stand-in</p>",
      }),
    );
    await page.goto("/invite#token=e2e-invite");
    await page.getByRole("link", { name: "Sign in with password" }).click();
    await page.waitForURL(/\/login\?next=%2Finvite$/);
    expect(page.url()).not.toContain("e2e-invite");
    expect(JSON.parse((await readStash(page)) ?? "{}")).toMatchObject({
      token: "e2e-invite",
    });
  });

  test("signed in as the invitee: one Accept button that sends only the token", async ({
    page,
    context,
    baseURL,
  }) => {
    await mockInvite(page, "Jesse@Example.com");
    await context.addCookies([
      { name: "csrf_token", value: "e2e-csrf", url: baseURL! },
    ]);
    let acceptBody: unknown = null;
    let csrfHeader: string | null = null;
    await page.route("**/api/v1/auth/invitations/accept", async (route) => {
      acceptBody = route.request().postDataJSON();
      csrfHeader = await route.request().headerValue("x-csrf-token");
      await route.fulfill(json({ detail: "Expired invitation" }, 403));
    });
    await page.goto("/invite#token=e2e-invite");
    const accept = page.getByRole("button", { name: "Accept invite" });
    await expect(accept).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Continue with Google" }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("link", { name: "Sign in with password" }),
    ).toHaveCount(0);
    await accept.click();
    await expect(page.getByText("Expired invitation")).toBeVisible();
    expect(acceptBody).toEqual({ token: "e2e-invite" });
    // The Gateway requires the double-submit pair when a session accepts.
    expect(csrfHeader).toBe("e2e-csrf");
  });
});
