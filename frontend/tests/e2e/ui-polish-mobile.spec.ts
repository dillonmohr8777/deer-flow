import { expect, test } from "@playwright/test";

import { MOCK_THREAD_ID, mockLangGraphAPI } from "./utils/mock-api";

test.describe("UI polish mobile regressions", () => {
  test("workspace exposes mobile sidebar navigation from the chat header", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");

    // A click that lands before hydration does nothing (the button is server
    // rendered), and this raced on the trunk too: retry until the sheet opens.
    await expect(async () => {
      await page.getByRole("button", { name: /toggle sidebar/i }).click();
      await expect(page.getByRole("link", { name: /new chat/i })).toBeVisible({
        timeout: 1_000,
      });
    }).toPass();
    await expect(page.getByRole("link", { name: /agents/i })).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
      .toBeLessThanOrEqual(375);
  });

  // f101/f118(e): the icon-only controls (display-mode toggle, new project,
  // trash) grow to the 44px phone floor, so their SidebarGroupLabel must grow
  // with them (`max-sm:h-11`) or the buttons spill 6px past the label's
  // default 32px (`h-8`) row.
  test("projects section controls fit inside their sidebar label on phones", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");
    await expect(async () => {
      await page.getByRole("button", { name: /toggle sidebar/i }).click();
      await expect(page.getByTestId("projects-new-project-button")).toBeVisible(
        { timeout: 1_000 },
      );
    }).toPass();

    const rows = await page.evaluate(() => {
      const buttons = [
        ...document.querySelectorAll(
          "[data-testid='projects-display-mode-toggle'], [data-testid='projects-new-project-button'], [data-testid='projects-trash-link']",
        ),
      ] as HTMLElement[];
      return buttons.map((button) => {
        const label = button.closest('[data-sidebar="group-label"]');
        const b = button.getBoundingClientRect();
        const l = label?.getBoundingClientRect();
        return {
          buttonHeight: b.height,
          labelHeight: l?.height ?? 0,
          overflowsTop: !l || b.top < l.top,
          overflowsBottom: !l || b.bottom > l.bottom,
        };
      });
    });
    expect(rows).toHaveLength(3);
    for (const row of rows) {
      expect(row.buttonHeight).toBeGreaterThanOrEqual(44);
      expect(row.labelHeight).toBeGreaterThanOrEqual(row.buttonHeight);
      expect(row.overflowsTop).toBe(false);
      expect(row.overflowsBottom).toBe(false);
    }
  });

  test("chat controls keep the 44px touch floor on phones", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Touch floor",
          messages: [
            {
              type: "human",
              id: "h1",
              content: [{ type: "text", text: "hi" }],
            },
            { type: "ai", id: "a1", content: "Ready when you are." },
          ],
        },
      ],
    });
    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await page.getByText("Ready when you are.").waitFor();

    // Header, message actions and composer tools: tooltip-wrapped buttons
    // used to slip past the phone rule at 32px.
    const small = await page.evaluate(() =>
      [
        ...document.querySelectorAll(
          "[data-chat-header] button, [data-chat-header] a, [data-chat-composer] button, [data-testid='main-message-list'] button",
        ),
      ]
        .filter((el) => (el as HTMLElement).offsetParent)
        .map((el) => {
          const b = el.getBoundingClientRect();
          return {
            label: el.getAttribute("aria-label"),
            w: b.width,
            h: b.height,
          };
        })
        .filter((b) => b.w < 44 || b.h < 44),
    );
    expect(small).toEqual([]);

    // The thread's Scheduled tasks link folds into Chat actions.
    await expect(
      page
        .locator("[data-chat-header]")
        .getByRole("link", { name: "Scheduled tasks" }),
    ).toBeHidden();
    await expect(async () => {
      await page.getByRole("button", { name: "Chat actions" }).click();
      await expect(
        page.getByRole("menuitem", { name: "Scheduled tasks" }),
      ).toHaveAttribute(
        "href",
        `/workspace/scheduled-tasks?thread_id=${MOCK_THREAD_ID}`,
        { timeout: 1_000 },
      );
    }).toPass();
    await expect(
      page.getByRole("menuitem", { name: "Export as Markdown" }),
    ).toBeVisible();
  });

  // Phone slips (below 640px) draw the Momo at 64px; Dillon Brain is a
  // layered box 64 by round(64 * 422/480) with no layer outside it. The
  // hairline roster from 640px keeps the 48px row avatar.
  for (const [width, motion, size] of [
    [390, "on", 64],
    [390, "reduced", 64],
    [700, "reduced", 48],
  ] as const) {
    test(`agents roster Momo is ${size}px at ${width} (motion ${motion})`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 844 });
      if (motion === "on") {
        // The workspace motion switch is off by default; turn it on.
        await page.addInitScript(() => {
          // Called with .call(this) below, so the unbound reference is intended.
          // eslint-disable-next-line @typescript-eslint/unbound-method
          const get = Storage.prototype.getItem;
          Storage.prototype.getItem = function (key: string) {
            return key.startsWith("momentum:appearance:v1:")
              ? JSON.stringify({ treatment: "paper", motion: true })
              : get.call(this, key);
          };
        });
      } else {
        await page.emulateMedia({ reducedMotion: "reduce" });
      }
      mockLangGraphAPI(page, {
        agents: [
          {
            name: "dillon-brain",
            description: "Leads the team.",
            tool_groups: [],
            skills: [],
          },
        ],
      });
      await page.goto("/workspace/agents");
      const slip = page.locator('li:has(h2:text-is("dillon-brain"))');
      const root = slip.locator('[data-paper-layers="root"]');
      await root.waitFor();
      await expect
        .poll(async () => Math.round((await root.boundingBox())!.width))
        .toBe(size);
      const box = (await root.boundingBox())!;
      expect(Math.round(box.height)).toBe(Math.round((size * 422) / 480));
      const kind = await root.evaluate((el) =>
        el.tagName === "IMG" ? "flat" : "layers",
      );
      expect(kind).toBe(motion === "on" ? "layers" : "flat");
      // 1px: the top layers' translateZ depth scales them a hair past the
      // box under perspective.
      const layers = await slip
        .locator('[data-paper-layers="root"] img')
        .evaluateAll((els) =>
          els.map((e) => e.getBoundingClientRect().toJSON()),
        );
      for (const b of layers) {
        expect(b.left).toBeGreaterThanOrEqual(box.x - 1);
        expect(b.top).toBeGreaterThanOrEqual(box.y - 1);
        expect(b.right).toBeLessThanOrEqual(box.x + box.width + 1);
        expect(b.bottom).toBeLessThanOrEqual(box.y + box.height + 1);
      }
    });
  }

  test("mobile artifacts open in a drawer without horizontal overflow", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Thread with artifact",
          artifacts: ["reports/mobile-summary.md"],
        },
      ],
    });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await page.getByTestId("artifact-trigger").click();

    await expect(
      page.getByRole("dialog", { name: /artifacts/i }),
    ).toBeVisible();
    await expect(page.getByText("mobile-summary.md")).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
      .toBeLessThanOrEqual(375);
  });

  test("global focus ring tokens are visible in light and dark themes", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await page.goto("/workspace/chats/new");

    const readRing = () =>
      page.evaluate(() =>
        getComputedStyle(document.documentElement)
          .getPropertyValue("--ring")
          .trim(),
      );

    await page.evaluate(() =>
      document.documentElement.classList.remove("dark"),
    );
    const lightRing = await readRing();
    expect(lightRing).not.toBe("transparent");
    expect(lightRing).not.toBe("");

    await page.evaluate(() => document.documentElement.classList.add("dark"));
    const darkRing = await readRing();
    expect(darkRing).not.toBe("transparent");
    expect(darkRing).not.toBe("");

    // The two themes must resolve to different ring tokens, otherwise the test
    // would pass trivially if <html> were stuck in one mode.
    expect(darkRing).not.toBe(lightRing);
  });

  test("chats search and tabs keep the page gutter on phones", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: "chat-1",
          title: "One chat to search",
          updated_at: new Date().toISOString(),
        },
      ],
    });

    await page.goto("/workspace/chats");

    const search = page.getByPlaceholder("Search chats");
    await expect(search).toBeVisible();
    const bounds = await search.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(12);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390 - 12);
  });

  test("chats page states use the shared paper states, not a bare page", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page, { threads: [] });
    const search = /\/api\/(?:langgraph\/)?threads\/search$/;
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => (release = resolve));
    await page.route(search, async (route) => {
      await held;
      await route.fallback();
    });

    await page.goto("/workspace/chats");
    // Loading says so, and offers no search over chats that are not here yet.
    await expect(
      page.getByRole("status").filter({ hasText: "Loading your chats" }),
    ).toBeVisible();
    await expect(page.getByPlaceholder("Search chats")).toHaveCount(0);

    release();
    // An empty Recent has nothing to search: the empty state is the page.
    await expect(page.getByText("No recent chats")).toBeVisible();
    await expect(page.getByPlaceholder("Search chats")).toHaveCount(0);

    // An empty Archived explains itself and leads back, one action.
    await page.getByRole("tab", { name: "Archived" }).click();
    await expect(
      page.getByText("No archived chats", { exact: true }),
    ).toBeVisible();
    const back = page.getByRole("button", { name: "Back to Recent chats" });
    expect((await back.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    await back.focus();
    await page.keyboard.press("Enter");
    const recent = page.getByRole("tab", { name: "Recent chats" });
    await expect(recent).toHaveAttribute("aria-selected", "true");
    // The button unmounts with the view; focus must land on the tab, not body.
    await expect(recent).toBeFocused();
  });

  test("a failed chats read is an ErrorState with Try again", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page, { threads: [] });
    await page.route(/\/api\/(?:langgraph\/)?threads\/search$/, (route) =>
      route.fulfill({ status: 500, json: { detail: "Upstream timed out" } }),
    );

    await page.goto("/workspace/chats");

    const alert = page.locator("[role=alert]:has([data-error-tag])");
    await expect(alert).toBeVisible({ timeout: 20_000 });
    await expect(alert).toContainText("Couldn't load your chats");
    await expect(alert).toContainText("Upstream timed out");
    const retry = alert.getByRole("button", { name: "Try again" });
    expect((await retry.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    await expect(page.getByPlaceholder("Search chats")).toHaveCount(0);
  });

  test("a failed chats read with no server reason stays in the page's locale", async ({
    page,
    context,
    baseURL,
  }) => {
    await context.addCookies([
      { name: "locale", value: "zh-CN", url: baseURL! },
    ]);
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page, { threads: [] });
    await page.route(/\/api\/(?:langgraph\/)?threads\/search$/, (route) =>
      route.fulfill({ status: 500, json: {} }),
    );

    await page.goto("/workspace/chats");

    const alert = page.locator("[role=alert]:has([data-error-tag])");
    await expect(alert).toBeVisible({ timeout: 20_000 });
    await expect(alert).toContainText("加载会话失败");
    await expect(alert).not.toContainText("Failed to load conversations");
  });

  test("chats page heads itself and files chats as slips on phones", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const threads = Array.from({ length: 8 }, (_, i) => ({
      thread_id: `chat-${i}`,
      title: `Chat number ${i}`,
      updated_at: new Date(Date.now() - i * 3_600_000).toISOString(),
    }));
    mockLangGraphAPI(page, { threads });

    await page.goto("/workspace/chats");

    await expect(
      page.getByRole("heading", { level: 1, name: "Chats" }),
    ).toBeVisible();
    const newChat = page.getByRole("link", { name: "New chat" }).first();
    expect((await newChat.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    // A phone would open its keyboard over the list.
    await expect(page.getByPlaceholder("Search chats")).not.toBeFocused();

    const row = page.getByRole("link", { name: "Chat number 0" }).locator("..");
    const slip = await row.evaluate((el) => {
      const s = getComputedStyle(el);
      return {
        left: s.borderLeftWidth,
        bg: s.backgroundColor,
        mb: s.marginBottom,
      };
    });
    expect(slip).toEqual({
      left: "1px",
      bg: "rgb(251, 248, 241)",
      mb: "12px",
    });

    // The page scrolls in its body, so the heading leaves and the list follows.
    await page
      .getByRole("link", { name: "Chat number 7" })
      .scrollIntoViewIfNeeded();
    expect(
      await page.evaluate(() => document.documentElement.scrollHeight),
    ).toBeLessThanOrEqual(844);
    await expect(
      page.getByRole("heading", { level: 1, name: "Chats" }),
    ).not.toBeInViewport();
  });

  test("chats are filed under day labels, in the text voice", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const day = 86_400_000;
    const at = (daysAgo: number) => {
      // Noon on the given calendar day, so the test never straddles midnight.
      const d = new Date(Date.now() - daysAgo * day);
      d.setHours(12, 0, 0, 0);
      return d.toISOString();
    };
    mockLangGraphAPI(page, {
      threads: [
        { thread_id: "t0", title: "Today chat", updated_at: at(0) },
        { thread_id: "t0b", title: "Another today chat", updated_at: at(0) },
        { thread_id: "t1", title: "Yesterday chat", updated_at: at(1) },
        { thread_id: "t3", title: "This week chat", updated_at: at(3) },
        { thread_id: "t400", title: "Old chat", updated_at: at(400) },
      ],
    });

    await page.goto("/workspace/chats");
    await expect(page.getByRole("link", { name: "Old chat" })).toBeAttached();

    const labels = page.locator("h2[data-day-group]");
    await expect(labels).toHaveText([
      "Today",
      "Yesterday",
      "Last 7 days",
      /^[A-Z][a-z]+ \d{4}$/,
    ]);
    // A label, not a heading voice: Nunito Sans at 11px, ink-muted.
    const style = await labels.first().evaluate((el) => {
      const s = getComputedStyle(el);
      return { font: s.fontFamily, size: s.fontSize, color: s.color };
    });
    expect(style.font).not.toMatch(/Fraunces/);
    expect(style.size).toBe("11px");
    expect(style.color).toBe("rgb(58, 74, 107)");
  });

  // d11 slice 14: a new chat on a phone keeps its composer at thumb reach
  // (it sat mid-screen, field top at 265 of 844) and its starters are 2px
  // paper tags at the 44px floor (they were 34px pills).
  test("a new chat keeps its composer and starters at thumb reach", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page, { threads: [] });

    await page.goto("/workspace/chats/new");

    const field = page.getByRole("textbox").first();
    await expect(field).toBeVisible({ timeout: 15_000 });
    await expect
      .poll(async () => (await field.boundingBox())!.y)
      .toBeGreaterThan(844 / 2);
    const starters = page.locator("[data-chat-starters] button");
    await expect(starters).toHaveCount(3);
    for (const starter of await starters.all()) {
      expect((await starter.boundingBox())!.height).toBeGreaterThanOrEqual(44);
      await expect(starter).toHaveCSS("border-radius", "2px");
    }
    // Two starters share the first row at 390, so the pile stays short.
    const first = (await starters.nth(0).boundingBox())!.y;
    const second = (await starters.nth(1).boundingBox())!.y;
    expect(Math.abs(first - second)).toBeLessThan(1);
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
      .toBeLessThanOrEqual(390);
  });

  // d11 slice 15: the composer's placeholder reads at full ink-muted (it was
  // 60%, about 3.1:1 on cream-hi), says what to write, and Send shares the
  // tools' row when there is no model picker (an empty 44px picker cost the
  // phone a whole row).
  test("a new chat's composer is two rows and its placeholder reads", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page, { threads: [] });

    await page.goto("/workspace/chats/new");

    const field = page.locator("textarea").first();
    await expect(field).toBeVisible({ timeout: 15_000 });
    await expect(field).toHaveAttribute(
      "placeholder",
      "Describe the job and what done looks like",
    );
    expect(
      await field.evaluate((el) => getComputedStyle(el, "::placeholder").color),
    ).toBe("rgb(58, 74, 107)");
    const send = page.getByRole("button", { name: "Send" });
    const attach = page.getByRole("button", { name: "Add attachments" });
    await expect
      .poll(async () => {
        const a = (await attach.boundingBox())!;
        const s = (await send.boundingBox())!;
        return Math.abs(a.y + a.height / 2 - (s.y + s.height / 2));
      })
      .toBeLessThan(2);
  });

  // Review of slice 15: the placeholder carries instructions, so it is no
  // longer the field's name; both composers are named "Message", and the
  // thread composer's own placeholder is pinned.
  test("the composer is named Message in a new chat and in a thread", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");
    const fresh = page.getByRole("textbox", { name: "Message" });
    await expect(fresh).toBeVisible({ timeout: 15_000 });
    await expect(fresh).toHaveAttribute(
      "placeholder",
      "Describe the job and what done looks like",
    );

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    const reply = page.getByRole("textbox", { name: "Message" });
    await expect(reply).toBeVisible({ timeout: 15_000 });
    await expect(reply).toHaveAttribute(
      "placeholder",
      "Reply, or give the next step",
    );
  });

  // Review of slice 15: the footer's row split waited on the models list,
  // so a phone with models configured grew a row (and moved Send) when
  // /api/models answered.
  test("Send holds still while the models list loads", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page, { threads: [] });
    await page.route("**/api/models", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          models: [
            {
              id: "alpha",
              name: "alpha",
              model: "alpha",
              display_name: "Alpha",
              supports_thinking: false,
              supports_reasoning_effort: false,
            },
          ],
          token_usage: { enabled: false },
        }),
      });
    });

    await page.goto("/workspace/chats/new");
    // The composer is bottom-anchored, so Send sits on the last row either
    // way; a late extra row shows as the tools row jumping up.
    const send = page.getByRole("button", { name: "Send" });
    const attach = page.getByRole("button", { name: "Add attachments" });
    await expect(send).toBeVisible({ timeout: 15_000 });
    const before = [
      (await send.boundingBox())!.y,
      (await attach.boundingBox())!.y,
    ];
    await expect(page.getByRole("button", { name: "Alpha" })).toBeVisible();
    const after = [
      (await send.boundingBox())!.y,
      (await attach.boundingBox())!.y,
    ];
    expect(Math.abs(after[0]! - before[0]!)).toBeLessThan(1);
    expect(Math.abs(after[1]! - before[1]!)).toBeLessThan(1);
  });

  // Review of slice 14: the welcome block is bottom-anchored, so on short
  // phones its Momo and greeting rose under the header (360x640 lost 71px,
  // 320x568 lost the Momo entirely).
  for (const [width, height] of [
    [360, 640],
    [320, 568],
    [375, 625],
    [414, 640],
    [375, 667],
    [360, 661],
    [568, 320],
  ] as const) {
    test(`a new chat's welcome stays below the header at ${width}x${height}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height });
      mockLangGraphAPI(page, { threads: [] });

      await page.goto("/workspace/chats/new");

      const greeting = page.getByRole("heading", {
        name: "What should the team take on?",
      });
      await expect(page.getByRole("textbox", { name: "Message" })).toBeVisible({
        timeout: 15_000,
      });
      // A landscape phone drops the welcome; every portrait phone keeps
      // the greeting.
      if (height <= 440) {
        await expect(greeting).toBeHidden();
        await expect(page.locator("[data-chat-starters]")).toBeHidden();
        const field = (await page
          .getByRole("textbox", { name: "Message" })
          .boundingBox())!;
        const top = await page
          .locator("header")
          .first()
          .evaluate((el) => el.getBoundingClientRect().bottom);
        expect(field.y).toBeGreaterThanOrEqual(top);
        return;
      }
      await expect(greeting).toBeVisible();
      const headerBottom = await page
        .locator("header")
        .first()
        .evaluate((el) => el.getBoundingClientRect().bottom);
      await expect
        .poll(() =>
          greeting.evaluate((el) => {
            const tops = [...el.parentElement!.children]
              .filter((child) => child.getClientRects().length > 0)
              .map((child) => child.getBoundingClientRect().top);
            return Math.min(...tops);
          }),
        )
        .toBeGreaterThanOrEqual(headerBottom);
      const starters = page.locator("[data-chat-starters]");
      const box = (await starters.boundingBox())!;
      expect(box.y + box.height).toBeLessThanOrEqual(height);
      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
        .toBeLessThanOrEqual(width);
    });
  }

  test("?settings=security opens the Security section", async ({ page }) => {
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new?settings=security");

    const dialog = page.getByRole("dialog", { name: "Settings" });
    await expect(
      dialog.getByRole("button", { name: "Security", exact: true }),
    ).toHaveAttribute("aria-current", "page");
    await expect(
      dialog.getByRole("heading", { name: "Two-factor authentication" }),
    ).toBeVisible();
  });
});

// Who is answering: an agent chat opens each reply turn with the agent's Momo
// and name, so a phone reader scrolled past the header still knows. The
// default chat's lead has no settled identity, so it draws none.
test.describe("assistant turn byline", () => {
  const turns = [
    { type: "human", id: "h1", content: [{ type: "text", text: "Draft it." }] },
    { type: "ai", id: "a1", content: "First draft." },
    { type: "human", id: "h2", content: [{ type: "text", text: "Shorter." }] },
    // A multi-group turn: a tool step, then the answer. Still one byline.
    {
      type: "ai",
      id: "a2-tool",
      content: "",
      tool_calls: [
        { id: "call-1", name: "web_search", args: { query: "memo length" } },
      ],
    },
    {
      type: "tool",
      id: "t2",
      tool_call_id: "call-1",
      name: "web_search",
      content: "[]",
    },
    { type: "ai", id: "a2", content: "Short draft." },
  ];

  test("agent chat signs every reply turn at 390px", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page, {
      agents: [{ name: "dillon-growth", display_name: "Growth" }],
      threads: [{ thread_id: MOCK_THREAD_ID, title: "Memo", messages: turns }],
    });
    await page.goto(`/workspace/agents/dillon-growth/chats/${MOCK_THREAD_ID}`);
    await page.getByText("Short draft.").waitFor();

    // One byline per turn, however many groups the turn renders.
    const bylines = page.locator("[data-turn-byline]");
    await expect(bylines).toHaveCount(2);
    await expect(bylines.first()).toHaveText("Growth");
    // The Momo is decorative beside the name, its box is 32px, and the
    // byline sits 12px above the reply's first line.
    await expect(
      bylines.first().locator("[aria-hidden='true'] [role='img']"),
    ).toHaveCount(1);
    const momoBox = await bylines
      .first()
      .locator("> [aria-hidden='true']")
      .evaluate((el) => el.getBoundingClientRect().height);
    expect(momoBox).toBe(32);
    const gap = await bylines.first().evaluate((el) => {
      const reply = el.parentElement!.querySelector(
        "p:not([data-turn-byline])",
      )!;
      return (
        reply.getBoundingClientRect().top - el.getBoundingClientRect().bottom
      );
    });
    expect(gap).toBeGreaterThanOrEqual(11);
    expect(gap).toBeLessThanOrEqual(13);
  });

  test("the default chat draws no byline", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page, {
      threads: [{ thread_id: MOCK_THREAD_ID, title: "Memo", messages: turns }],
    });
    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await page.getByText("Short draft.").waitFor();
    await expect(page.locator("[data-turn-byline]")).toHaveCount(0);
  });
});

test.describe("scheduled tasks on a phone", () => {
  const task = (id: string, title: string) => ({
    id,
    thread_id: null,
    title,
    prompt: "Draft it and cite the source.",
    schedule_type: "cron" as const,
    schedule_spec: { cron: "0 9 * * *" },
    timezone: "UTC",
    status: "enabled" as const,
    next_run_at: null,
    last_run_at: null,
    last_run_id: null,
    last_error: null,
    run_count: 0,
    context_mode: "fresh_thread_per_run" as const,
    assistant_id: null,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
  });

  test("the page scrolls inside the body and a tapped task comes to hand", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page, {
      threads: [],
      scheduledTasks: [
        task("a", "Weekly SEO report draft"),
        task("b", "Monday ad spend check"),
        task("c", "Review replies waiting in the inbox"),
      ],
    });
    await page.goto("/workspace/scheduled-tasks");
    const second = page.getByTestId("scheduled-task-item-b");
    await second.waitFor();

    // The document itself never scrolls: before, it ran 1269px past the
    // viewport, so the tab bar scrolled away and content painted over it.
    await expect
      .poll(() =>
        page.evaluate(
          () => document.documentElement.scrollHeight - window.innerHeight,
        ),
      )
      .toBeLessThanOrEqual(0);

    // A tap brings the sheet into view with focus on its title; before, the
    // sheet changed below the fold and the tap looked like it did nothing.
    await expect(async () => {
      await second.click();
      await expect(
        page.getByRole("heading", { level: 2, name: "Monday ad spend check" }),
      ).toBeFocused({ timeout: 1_000 });
    }).toPass();
    await expect(page.getByTestId("scheduled-task-detail")).toBeInViewport();

    const small = await page.evaluate(() =>
      [
        ...document.querySelectorAll(
          "[data-testid='scheduled-task-detail'] button, [data-testid='scheduled-task-create-form'] button, [aria-pressed]",
        ),
      ]
        .filter((el) => (el as HTMLElement).offsetParent)
        .filter((el) => el.getBoundingClientRect().height < 44)
        .map(
          (el) => (el as HTMLElement).innerText || el.outerHTML.slice(0, 160),
        ),
    );
    expect(small).toEqual([]);
  });

  test("filters are one-row rails and tasks are slips that name a failure", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page, {
      threads: [],
      scheduledTasks: [
        task("a", "Weekly SEO report draft"),
        {
          ...task("b", "Monday ad spend check"),
          last_error: "Google Ads token expired, reconnect the account",
        },
      ],
    });
    await page.goto("/workspace/scheduled-tasks");
    await page.getByTestId("scheduled-task-item-b").waitFor();

    // An enabled task can still be failing: the row says so without a tap.
    await expect(page.getByTestId("scheduled-task-item-b")).toContainText(
      "Google Ads token expired",
    );

    const facts = await page.evaluate(() => {
      const rails = [
        ...document.querySelectorAll("[role='group'][aria-label]"),
      ].filter((g) => g.querySelector("[aria-pressed]"));
      const list = document.querySelector(
        "[data-testid='scheduled-task-list']",
      )!;
      const slips = [...list.querySelectorAll("li")].map((li) =>
        li.getBoundingClientRect(),
      );
      return {
        // Before, Status wrapped to two rows and the pair stood 200px tall.
        railHeights: rails.map((g) =>
          Math.round(g.getBoundingClientRect().height),
        ),
        // The rail sizes to the column, so the page keeps its 16px gutter.
        listRight: Math.round(list.getBoundingClientRect().right),
        slipGap: Math.round(slips[1]!.top - slips[0]!.bottom),
      };
    });
    expect(facts.railHeights.length).toBeGreaterThanOrEqual(2);
    for (const h of facts.railHeights) expect(h).toBeLessThanOrEqual(56);
    expect(facts.listRight).toBeLessThanOrEqual(390 - 16);
    expect(facts.slipGap).toBeGreaterThanOrEqual(8);
  });

  // The failure names itself in the row at every width, not only on phones.
  for (const width of [430, 1440]) {
    test(`a failing task's row names the failure at ${width}px`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      mockLangGraphAPI(page, {
        threads: [],
        scheduledTasks: [
          {
            ...task("b", "Monday ad spend check"),
            last_error: "Google Ads token expired, reconnect the account",
          },
        ],
      });
      await page.goto("/workspace/scheduled-tasks");
      await expect(page.getByTestId("scheduled-task-item-b")).toContainText(
        "Google Ads token expired",
      );
    });
  }
});

// A filter rail's negative margin is sideways only: a block margin would
// cancel the space-y gap its parent puts under it, and on Tools &
// integrations the category rail sat flush on the next control (-5px).
test("a filter rail keeps its parent's gap below it at 390px", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  mockLangGraphAPI(page);
  await page.goto("/workspace/capabilities");
  const rail = page.getByRole("group", { name: "All categories" });
  await rail.waitFor();
  const gap = () =>
    rail.evaluate((group) => {
      const visibleNext = (el: Element) => {
        let next = el.nextElementSibling;
        while (next?.getBoundingClientRect().height === 0) {
          next = next.nextElementSibling;
        }
        return next;
      };
      // Climb to the block the parent spaces (FilterGroup may wrap the rail).
      let el: Element | null = group;
      while (el && !visibleNext(el)) el = el.parentElement;
      const next = el && visibleNext(el);
      return el && next
        ? next.getBoundingClientRect().top - el.getBoundingClientRect().bottom
        : null;
    });
  // Poll: the block under the rail renders once the catalog loads.
  await expect.poll(gap).toBeGreaterThanOrEqual(16);
});
