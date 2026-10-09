import { expect, test, type Page, type Route } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const json = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const CHANNELS = [
  {
    id: "c-general",
    slug: "general",
    name: "General",
    topic: "Anything the whole team should see.",
    created_at: "2026-09-25T12:00:00Z",
  },
  {
    id: "c-sales",
    slug: "sales",
    name: "Sales",
    topic: "Leads, pitches and pipeline.",
    created_at: "2026-09-25T12:00:01Z",
  },
];

function lesson(id: string, title: string, videoSlot: string | null = null) {
  return {
    id,
    title,
    minutes: 5,
    summary: `${title} summary.`,
    steps: ["Name the client first.", "Say draft only."],
    try_it: `Try ${title}.`,
    video_slot: videoSlot,
    video_url: null,
    completed: false,
  };
}

/** Mock the Momentum-internal APIs; ``internal`` drives the feature flag. */
async function mockInternal(
  page: Page,
  { internal = true }: { internal?: boolean } = {},
) {
  mockLangGraphAPI(page, { scheduledTasks: [] });
  await page.route("**/api/features", (route) =>
    route.fulfill(
      json({
        agents_api: { enabled: true },
        desk: { enabled: internal },
        momentum_internal: { enabled: internal },
      }),
    ),
  );

  const messages: Record<
    string,
    {
      id: string;
      channel_id: string;
      author_user_id: string;
      body: string;
      created_at: string;
    }[]
  > = {
    "c-general": [
      {
        id: "m1",
        channel_id: "c-general",
        author_user_id: "u-jesse",
        body: "Morning team",
        created_at: "2026-09-25T13:00:00Z",
      },
    ],
    "c-sales": [],
  };
  const posted: { channel: string; body: string }[] = [];

  await page.route("**/api/team/channels", (route) =>
    route.fulfill(
      internal
        ? json({ channels: CHANNELS })
        : json({ detail: "Not found" }, 404),
    ),
  );
  await page.route("**/api/team/members", (route) =>
    route.fulfill(
      json({
        members: [
          { user_id: "default", email: "default@test.local", role: "member" },
          {
            user_id: "u-jesse",
            email: "jesse@momentum.example",
            role: "member",
          },
        ],
      }),
    ),
  );
  await page.route("**/api/team/channels/*/messages*", async (route: Route) => {
    const channel = new URL(route.request().url()).pathname.split("/")[4]!;
    if (route.request().method() === "POST") {
      const { body } = route.request().postDataJSON() as { body: string };
      posted.push({ channel, body });
      const message = {
        id: `p${posted.length}`,
        channel_id: channel,
        author_user_id: "default",
        body,
        created_at: new Date().toISOString(),
      };
      (messages[channel] ??= []).push(message);
      return route.fulfill({ ...json(message), status: 201 });
    }
    return route.fulfill(json({ messages: messages[channel] ?? [] }));
  });

  const progress: { lesson: string; completed: boolean }[] = [];
  // Stateful like the real API: GET reflects every PUT so far.
  const done = new Set<string>();
  await page.route("**/api/academy", (route) => {
    const lessons = [
      lesson("momobot-01-meet-momo", "Meet Momo", "momo-01"),
      lesson(
        "momobot-02-prompting",
        "Prompt like an account manager",
        "momo-02",
      ),
    ].map((l) => ({ ...l, completed: done.has(l.id) }));
    return route.fulfill(
      json({
        tracks: [
          {
            id: "momobot",
            title: "MomoBot, start to finish",
            summary: "Start here.",
            lessons,
          },
        ],
        completed_count: done.size,
        lesson_count: lessons.length,
      }),
    );
  });
  await page.route("**/api/academy/lessons/*/progress", async (route) => {
    const id = new URL(route.request().url()).pathname.split("/")[4]!;
    const { completed } = route.request().postDataJSON() as {
      completed: boolean;
    };
    progress.push({ lesson: id, completed });
    if (completed) done.add(id);
    else done.delete(id);
    return route.fulfill({ status: 204, body: "" });
  });

  return { posted, progress };
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

test.describe("Team channels", () => {
  test("staff read a channel, switch channels, and post as themselves", async ({
    page,
  }) => {
    const { posted } = await mockInternal(page);
    await page.goto("/workspace/team");

    const board = page.getByTestId("team-board");
    await expect(
      board.getByRole("heading", { name: "Team", level: 1 }),
    ).toBeVisible();
    await expect(board.getByText("Morning team")).toBeVisible();
    await expect(board.getByText("jesse", { exact: true })).toBeVisible();

    // Members don't see channel management; the API enforces the same rule.
    await expect(page.getByLabel("Add a channel")).toHaveCount(0);

    // A half-typed message doesn't follow you into another channel.
    const composer = page.getByLabel("Message #general");
    await composer.fill("draft for general");
    await page.getByRole("button", { name: "sales", exact: true }).click();
    await expect(page.getByLabel("Message #sales")).toHaveValue("");

    await page.getByLabel("Message #sales").fill("New lead from Intelligence");
    await page.keyboard.press("Enter");
    await expect(board.getByText("New lead from Intelligence")).toBeVisible();
    expect(posted).toEqual([
      { channel: "c-sales", body: "New lead from Intelligence" },
    ]);
  });

  test("anyone who isn't Momentum staff is sent away", async ({ page }) => {
    await mockInternal(page, { internal: false });
    await page.goto("/workspace/team");
    await expect(page).toHaveURL(/\/workspace\/command-center/);
    await expect(page.getByRole("link", { name: "Team" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "AI Academy" })).toHaveCount(0);
  });
});

test.describe("AI Academy", () => {
  test("staff open a lesson, see the video slot, and mark it done", async ({
    page,
  }) => {
    const { progress } = await mockInternal(page);
    await page.goto("/workspace/academy");

    const academy = page.getByTestId("academy");
    await expect(
      academy.getByRole("heading", { name: "AI Academy", level: 1 }),
    ).toBeVisible();
    await expect(academy.getByText("0 of 2 lessons done")).toBeVisible();

    await academy.getByText("Meet Momo", { exact: true }).click();
    await expect(
      page
        .locator("#lesson-momobot-01-meet-momo")
        .getByText("Momo explainer video for this lesson is in production."),
    ).toBeVisible();
    await expect(academy.getByText("Try Meet Momo.")).toBeVisible();

    await academy.getByLabel("Mark this lesson done").first().check();
    await expect(academy.getByText("1 of 2 lessons done")).toBeVisible();
    expect(progress).toEqual([
      { lesson: "momobot-01-meet-momo", completed: true },
    ]);
  });

  test("a client-facing instance never shows the Academy", async ({ page }) => {
    await mockInternal(page, { internal: false });
    await page.goto("/workspace/academy");
    await expect(page).toHaveURL(/\/workspace\/command-center/);
  });
});

test.describe("Team and Academy layout", () => {
  for (const width of [390, 768, 1440]) {
    test(`no horizontal overflow at ${width}px`, async ({ page }) => {
      await mockInternal(page);
      await page.setViewportSize({ width, height: 900 });
      for (const path of ["/workspace/team", "/workspace/academy"]) {
        await page.goto(path);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        await expectNoHorizontalOverflow(page);
      }
    });
  }
});
