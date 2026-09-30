import { expect, test, type Locator, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const ROOM_PATH = "/workspace/desk/agent-room";
const MESSAGE = {
  id: "review-message",
  user_id: "default",
  author_kind: "agent",
  agent_id: "reviewer",
  agent_role: "Independent Reviewer",
  message_type: "finding",
  body: `Saved source evidence: ${"a".repeat(1000)}`,
  run_id: "review-run",
  created_at: "2026-09-29T14:00:00Z",
};

async function mockRoom(
  page: Page,
  { enabled = true, rejectPost = false } = {},
) {
  // Unhandled API reads fail locally; this fixture never reaches a real worker.
  await page.route("**/api/**", (route) =>
    route.fulfill({ status: 404, json: { detail: "Not found" } }),
  );
  mockLangGraphAPI(page, {
    threads: [{ thread_id: "phone-thread", title: "Phone task" }],
    projects: [{ id: "phone-project", name: "Phone project" }],
  });
  await page.route("**/api/features", (route) =>
    route.fulfill({
      json: { agents_api: { enabled: true }, desk: { enabled } },
    }),
  );
  await page.route("**/api/workspaces", (route) =>
    route.fulfill({ json: { workspaces: [], active_workspace_id: null } }),
  );
  await page.route("**/api/plugins", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/console/stats", (route) =>
    route.fulfill({ json: { active_runs: 0 } }),
  );
  await page.route("**/api/console/runs*", (route) =>
    route.fulfill({ json: { runs: [], has_more: false } }),
  );
  await page.route("**/api/board/threads*", (route) =>
    route.fulfill({ json: { threads: [] } }),
  );
  const posts: unknown[] = [];
  await page.route("**/api/agent-room/messages*", (route) => {
    if (!enabled)
      return route.fulfill({ status: 404, json: { detail: "Not found" } });
    if (route.request().method() === "POST") {
      const input = route.request().postDataJSON() as {
        body: string;
        message_type: string;
      };
      posts.push(input);
      if (rejectPost)
        return route.fulfill({
          status: 403,
          json: { detail: "Room posting is unavailable" },
        });
      return route.fulfill({
        status: 201,
        json: {
          ...MESSAGE,
          ...input,
          id: "owner-instruction",
          author_kind: "owner",
          agent_id: null,
          agent_role: "",
          run_id: null,
        },
      });
    }
    return route.fulfill({ json: { messages: [MESSAGE] } });
  });
  return posts;
}

async function expectTouchTarget(locator: Locator) {
  const box = await locator.boundingBox();
  expect(box, "visible touch target").not.toBeNull();
  expect(box!.height).toBeGreaterThanOrEqual(44);
  expect(box!.width).toBeGreaterThanOrEqual(44);
}

for (const width of [390, 768, 1440]) {
  test(`room has no horizontal overflow at ${width}px and phone targets remain accessible`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await mockRoom(page);
    await page.goto(ROOM_PATH);
    await expect(
      page.getByRole("heading", { name: "Agent Room" }),
    ).toBeVisible();
    await expect(page.getByText(MESSAGE.body, { exact: true })).toBeVisible();
    const submit = page.getByRole("button", { name: "Post to room" });
    await expect(submit).toBeDisabled();
    await expectTouchTarget(submit);
    expect(
      await page.evaluate(() =>
        Math.max(
          document.body.scrollWidth,
          document.documentElement.scrollWidth,
        ),
      ),
    ).toBeLessThanOrEqual(width);
    await page.screenshot({
      path: testInfo.outputPath(`agent-room-${width}.png`),
      fullPage: true,
    });
    await submit.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: testInfo.outputPath(`agent-room-activity-${width}.png`),
      fullPage: true,
    });
    if (width === 390) {
      const menu = page
        .locator("header")
        .getByRole("button", { name: "Toggle Sidebar" });
      await expectTouchTarget(menu);
      await expectTouchTarget(
        page.locator("header").getByRole("button", { name: /Background work/ }),
      );
      await menu.click();
      const drawer = page.locator('[data-mobile="true"]');
      await expect(drawer).toBeVisible();
      await expect
        .poll(async () => Math.round((await drawer.boundingBox())?.x ?? -1))
        .toBe(0);
      await expect(
        drawer.getByRole("link", { name: "Agent Room", exact: true }),
      ).toBeVisible();
      const controls = drawer.locator(
        "button:visible, a[href]:visible, select:visible",
      );
      expect(await controls.count()).toBeGreaterThan(8);
      for (const control of await controls.all())
        await expectTouchTarget(control);
      await page.screenshot({
        path: testInfo.outputPath("agent-room-phone-drawer.png"),
        fullPage: true,
      });
      const action = drawer
        .locator('[data-slot="sidebar-menu-action"]')
        .first();
      if (await action.isVisible()) {
        const actionBox = await action.boundingBox();
        const rowBox = await action.locator("..").boundingBox();
        expect(actionBox!.y).toBeGreaterThanOrEqual(rowBox!.y);
        expect(actionBox!.y + actionBox!.height).toBeLessThanOrEqual(
          rowBox!.y + rowBox!.height,
        );
      }
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(width);
    }
  });
}

test("owner instruction is trimmed, posted once and read back in the feed", async ({
  page,
}) => {
  const posts = await mockRoom(page);
  await page.goto(ROOM_PATH);
  await expect(page.getByRole("heading", { name: "Agent Room" })).toBeVisible();
  await page
    .getByLabel("Leave an instruction or note")
    .fill("  Verify the saved artifact  ");
  await page.getByRole("button", { name: "Post to room" }).click();
  await expect(
    page.getByText("Verify the saved artifact", { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Leave an instruction or note")).toHaveValue("");
  expect(posts).toEqual([
    { body: "Verify the saved artifact", message_type: "instruction" },
  ]);
});

test("failed owner post keeps the draft and does not invent a delivered message", async ({
  page,
}) => {
  const posts = await mockRoom(page, { rejectPost: true });
  await page.goto(ROOM_PATH);
  await page
    .getByLabel("Leave an instruction or note")
    .fill("Retain this failed draft");
  await page.getByRole("button", { name: "Post to room" }).click();
  await expect(page.locator("form").getByRole("alert")).toContainText(
    "Room posting is unavailable",
  );
  await expect(page.getByLabel("Leave an instruction or note")).toHaveValue(
    "Retain this failed draft",
  );
  await expect(
    page.locator("article").getByText("Retain this failed draft"),
  ).toHaveCount(0);
  expect(posts).toHaveLength(1);
});

test("disabled private Desk redirects without exposing the room or its composer", async ({
  page,
}) => {
  const posts = await mockRoom(page, { enabled: false });
  await page.goto(ROOM_PATH);
  await expect(page).toHaveURL(/\/workspace\/command-center$/);
  await expect(page.getByRole("heading", { name: "Agent Room" })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("link", { name: "Agent Room", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Post to room" })).toHaveCount(
    0,
  );
  expect(posts).toHaveLength(0);
});
