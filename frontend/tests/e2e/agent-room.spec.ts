import { expect, test, type Locator, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const ROOM_PATH = "/workspace/desk/agent-room";

// Resolve the actual rendered colours, including OKLCH and transparent parents.
// This catches a light-treatment selector winning after dark mode is selected.
async function roomTextContrast(page: Page) {
  return page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 1;
    const context = canvas.getContext("2d")!;
    const rgba = (color: string) => {
      context.clearRect(0, 0, 1, 1);
      context.fillStyle = color;
      context.fillRect(0, 0, 1, 1);
      return [...context.getImageData(0, 0, 1, 1).data];
    };
    const mix = (front: number[], back: number[]) => {
      const alpha = front[3]! / 255;
      return front
        .slice(0, 3)
        .map((v, i) => v * alpha + back[i]! * (1 - alpha));
    };
    const luminance = (color: number[]) => {
      const linear = color.map((v) => {
        const s = v / 255;
        return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
      });
      return linear[0]! * 0.2126 + linear[1]! * 0.7152 + linear[2]! * 0.0722;
    };
    return [
      ...document.querySelectorAll(
        "main h1,main h2,main h3,main p,main time,main label,main span,main strong,main textarea,main button,main a,main input",
      ),
    ]
      .filter(
        (element) =>
          element.getClientRects().length > 0 &&
          (element.textContent?.trim() || element.tagName === "TEXTAREA"),
      )
      .map((element) => {
        const parents: Element[] = [];
        for (
          let parent: Element | null = element;
          parent;
          parent = parent.parentElement
        )
          parents.unshift(parent);
        let background = [255, 255, 255];
        let parentBackground = background;
        for (const parent of parents) {
          parentBackground = background;
          background = mix(
            rgba(getComputedStyle(parent).backgroundColor),
            background,
          );
        }
        let foreground = mix(rgba(getComputedStyle(element).color), background);
        const opacity = Number(getComputedStyle(element).opacity);
        foreground = foreground.map(
          (v, i) => v * opacity + parentBackground[i]! * (1 - opacity),
        );
        background = background.map(
          (v, i) => v * opacity + parentBackground[i]! * (1 - opacity),
        );
        const a = luminance(foreground),
          b = luminance(background);
        return {
          text: element.textContent?.trim().slice(0, 70) ?? "textarea",
          foreground,
          background,
          ratio: (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05),
        };
      });
  });
}
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

for (const theme of ["light", "dark"]) {
  for (const width of [390, 768, 1440]) {
    test(`paper room text stays readable in ${theme} at ${width}px`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.addInitScript(
        (theme) => localStorage.setItem("theme", theme),
        theme,
      );
      await mockRoom(page);
      await page.goto(ROOM_PATH);
      await expect(
        page.getByRole("heading", { name: "Agent Room" }),
      ).toBeVisible();
      await expect(page.locator("html")).toHaveAttribute(
        "data-treatment",
        "paper",
      );
      const readings = await roomTextContrast(page);
      expect(readings.length).toBeGreaterThan(15);
      expect(readings.filter((reading) => reading.ratio < 4.5)).toEqual([]);
    });
  }
  for (const treatment of ["classic", "current", "space", "future", "retro"]) {
    test(`${treatment} room text stays readable in ${theme}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: 390, height: 900 });
      await page.addInitScript(
        ({ theme, treatment }) => {
          localStorage.setItem("theme", theme);
          localStorage.setItem(
            "momentum:appearance:v1:default",
            JSON.stringify({ treatment, motion: false }),
          );
        },
        { theme, treatment },
      );
      await mockRoom(page);
      await page.goto(ROOM_PATH);
      await expect(
        page.getByRole("heading", { name: "Agent Room" }),
      ).toBeVisible();
      await expect(page.locator("html")).toHaveAttribute(
        "data-treatment",
        treatment,
      );
      const readings = await roomTextContrast(page);
      expect(readings.filter((reading) => reading.ratio < 4.5)).toEqual([]);
    });
  }
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
