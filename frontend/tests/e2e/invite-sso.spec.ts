import { expect, test, type Page } from "@playwright/test";

const json = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const invite = {
  email: "jesse@example.com",
  workspace_name: "Momentum",
  expires_at: "2026-10-01T00:00:00Z",
  requires_login: true,
  sign_in: "sso",
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

test.describe("invite with Google sign-in", () => {
  for (const width of [390, 1440]) {
    test(`signed out: offers Continue with Google at ${width}px`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      await mockInvite(page, null);
      await page.goto("/invite#token=e2e-invite");

      const button = page.getByRole("button", {
        name: "Continue with Google",
      });
      await expect(button).toBeVisible();
      await expect(
        page.getByText("Sign in as jesse@example.com to accept."),
      ).toBeVisible();
      await expect(page.getByLabel(/password/i)).toHaveCount(0);
      const box = await button.boundingBox();
      expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
      const overflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
      await page.screenshot({
        path: test.info().outputPath(`invite-sso-${width}.png`),
      });

      // The token leaves the fragment for session storage, never a URL.
      const started = page.waitForRequest(/\/api\/v1\/auth\/oauth\/google/);
      await page.route("**/api/v1/auth/oauth/google**", (route) =>
        route.fulfill({ status: 200, body: "ok" }),
      );
      await button.click();
      const request = await started;
      expect(request.url()).toContain("next=%2Finvite");
      expect(request.url()).not.toContain("e2e-invite");
    });
  }

  test("signed in as the invitee: one Accept button", async ({ page }) => {
    await mockInvite(page, "jesse@example.com");
    let acceptBody: unknown = null;
    await page.route("**/api/v1/auth/invitations/accept", async (route) => {
      acceptBody = route.request().postDataJSON();
      await route.fulfill(json({ detail: "Expired invitation" }, 403));
    });
    await page.goto("/invite#token=e2e-invite");
    await page.getByRole("button", { name: "Accept invite" }).click();
    await expect(page.getByText("Expired invitation")).toBeVisible();
    expect(acceptBody).toEqual({ token: "e2e-invite" });
  });
});
