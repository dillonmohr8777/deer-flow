import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const TOKEN = "tok_e2e_SECRET-123";

async function openInvite(page: Page) {
  await page.goto("/workspace/chats/new");
  const settingsMenu = page
    .getByRole("button", { name: /Settings and more/ })
    .first();
  if (!(await settingsMenu.isVisible())) {
    await page.locator("[data-sidebar='trigger']:visible").first().click();
  }
  await settingsMenu.click();
  await page.getByRole("menuitem", { name: "Settings", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Settings", exact: true });
  await dialog
    .getByRole("button", { name: "Invite teammate", exact: true })
    .click();
  return dialog;
}

async function mockInviteAPI(page: Page) {
  mockLangGraphAPI(page);
  await page.route("**/api/workspaces", (route) =>
    route.fulfill({
      json: {
        workspaces: [
          { id: "org-a", name: "Momentum", role: "owner" },
          { id: "org-b", name: "Client Co", role: "member" },
        ],
        active_workspace_id: "org-a",
      },
    }),
  );
  await page.route("**/api/v1/auth/invitations", (route) => {
    expect(route.request().method()).toBe("POST");
    expect(route.request().postDataJSON()).toEqual({
      organization_id: "org-a",
      email: "new@example.com",
      role: "member",
    });
    return route.fulfill({
      status: 201,
      json: {
        id: "inv-1",
        token: TOKEN,
        expires_at: "2026-10-01T12:00:00Z",
        email: "new@example.com",
        workspace_name: "Momentum",
      },
    });
  });
}

for (const width of [390, 768, 1440]) {
  test(`invite form mints a one-time link without overflow at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockInviteAPI(page);
    const dialog = await openInvite(page);

    const email = dialog.getByLabel("Email");
    await expect(email).toBeVisible();
    await expect(dialog.getByLabel("Workspace")).toHaveValue("org-a");
    await expect(dialog.getByLabel("Role")).toHaveValue("member");

    for (const control of [
      email,
      dialog.getByLabel("Workspace"),
      dialog.getByLabel("Role"),
      dialog.getByRole("button", { name: "Create invite link" }),
    ]) {
      const box = await control.boundingBox();
      expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
    }

    await email.fill("new@example.com");
    await dialog.getByRole("button", { name: "Create invite link" }).click();

    const link = dialog.getByLabel("Invite link");
    await expect(link).toHaveValue(new RegExp(`/invite#token=${TOKEN}$`));
    await expect(dialog.getByText(/Shown once/)).toBeVisible();
    await expect(
      dialog.getByRole("button", { name: "Copy link" }),
    ).toBeVisible();

    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    const dialogOverflow = await dialog.evaluate(
      (node) => node.scrollWidth - node.clientWidth,
    );
    expect(dialogOverflow).toBeLessThanOrEqual(0);

    expect(page.url()).not.toContain(TOKEN);
    const stored = await page.evaluate(() =>
      JSON.stringify([
        Object.entries(window.localStorage),
        Object.entries(window.sessionStorage),
      ]),
    );
    expect(stored).not.toContain(TOKEN);
  });
}

test("invite form explains it to a non-admin", async ({ page }) => {
  mockLangGraphAPI(page);
  await page.route("**/api/workspaces", (route) =>
    route.fulfill({
      json: {
        workspaces: [{ id: "org-b", name: "Client Co", role: "member" }],
        active_workspace_id: "org-b",
      },
    }),
  );
  const dialog = await openInvite(page);
  await expect(
    dialog.getByText(/Only an owner or admin of a shared workspace/),
  ).toBeVisible();
  await expect(dialog.getByLabel("Email")).toHaveCount(0);
});
