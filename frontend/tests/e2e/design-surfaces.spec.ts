/**
 * Design-review screenshot harness. Not a regression test: it is skipped
 * unless DESIGN_SHOTS=1, and it asserts nothing beyond "the page rendered".
 *
 *   DESIGN_SHOTS=1 DESIGN_SHOTS_DIR=<dir> pnpm exec playwright test design-surfaces
 *
 * Signed-in surfaces run against the normal auth-disabled e2e server, with
 * every backend call answered by page.route() mocks. /login redirects away
 * while auth is disabled, so it is captured from DESIGN_SIGNED_OUT_URL: the
 * same build started with DEER_FLOW_AUTH_DISABLED=0 and an unreachable
 * gateway (see playwright.auth.config.ts). Without that URL it is skipped.
 */
import { mkdirSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { MOCK_THREAD_ID, mockLangGraphAPI } from "./utils/mock-api";

const enabled = process.env.DESIGN_SHOTS === "1";
const outDir = process.env.DESIGN_SHOTS_DIR ?? "test-results/design-shots";
const signedOutURL = process.env.DESIGN_SIGNED_OUT_URL;
// Comma-separated surface names to capture, e.g. "command-center,chat-thread".
const only = process.env.DESIGN_SHOTS_ONLY?.split(",").filter(Boolean);
const wanted = (name: string) => !only || only.includes(name);

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
] as const;

const PROJECT_ID = "11111111-1111-1111-1111-111111111111";
const NOW = "2026-09-24T14:00:00Z";
const minutesAgo = (minutes: number) =>
  new Date(Date.parse(NOW) - minutes * 60_000).toISOString();

const MODELS = [
  {
    id: "claude-sonnet",
    name: "claude-sonnet",
    model: "claude-sonnet-4-5",
    display_name: "Claude Sonnet",
    supports_thinking: true,
    supports_reasoning_effort: true,
  },
  {
    id: "gpt-5-mini",
    name: "gpt-5-mini",
    model: "gpt-5-mini",
    display_name: "GPT-5 mini",
  },
];

const AGENTS = [
  {
    name: "dillon-brain",
    display_name: "Dillon Brain",
    description:
      "Lead agent. Plans client work, delegates to specialists and reports back with receipts.",
    model: "claude-sonnet",
    tool_groups: null,
    skills: null,
  },
  {
    name: "omega-reporting",
    display_name: "Omega weekly reporting",
    description: "Builds the Monday performance summary for Omega Landscaping.",
    model: "gpt-5-mini",
    tool_groups: ["web", "file:read"],
    skills: ["data-analysis"],
  },
];

const SUBAGENT_NAMES = [
  [
    "dillon-growth",
    "Growth",
    "Campaign ideas, landing page tests and paid search audits.",
  ],
  [
    "dillon-builder",
    "Builder",
    "Builds and verifies websites, internal tools and automations.",
  ],
  [
    "dillon-intelligence",
    "Intelligence",
    "Researches evidence and resolves conflicting sources.",
  ],
  [
    "dillon-critic",
    "Critic",
    "Independently checks deliverables against the brief.",
  ],
  [
    "dillon-revenue",
    "Revenue",
    "Reconciles leads, invoices and collected revenue.",
  ],
  [
    "dillon-reliability",
    "Reliability",
    "Audits runs, missing artifacts and stalled work.",
  ],
  [
    "dillon-client-operations",
    "Client operations",
    "Onboarding, reporting and delivery packages.",
  ],
] as const;

const SUBAGENTS = SUBAGENT_NAMES.map(([name, display, description]) => ({
  name,
  display_name: display,
  description,
  system_prompt: null,
  tools: null,
  disallowed_tools: null,
  skills: null,
  model: "claude-sonnet",
  max_turns: 40,
  timeout_seconds: 900,
  enabled: true,
  source: "managed",
  editable: true,
  conflict: false,
  config_overrides: {},
}));

const RUNS = [
  {
    run_id: "run-0001",
    thread_id: MOCK_THREAD_ID,
    thread_title: "Omega Landscaping September lead review",
    assistant_id: "dillon-brain",
    status: "running",
    model_name: "claude-sonnet",
    created_at: minutesAgo(3),
    updated_at: minutesAgo(1),
    duration_seconds: null,
    total_tokens: 18_422,
    message_count: 9,
    cost: null,
    error: null,
  },
  {
    run_id: "run-0002",
    thread_id: "thread-0002",
    thread_title: "Draft the Q4 paid search budget memo",
    assistant_id: "dillon-growth",
    status: "success",
    model_name: "claude-sonnet",
    created_at: minutesAgo(52),
    updated_at: minutesAgo(47),
    duration_seconds: 284,
    total_tokens: 41_907,
    message_count: 14,
    cost: 0.4213,
    error: null,
  },
  {
    run_id: "run-0003",
    thread_id: "thread-0003",
    thread_title: "Rebuild the Bridge directory search page",
    assistant_id: "dillon-builder",
    status: "error",
    model_name: "gpt-5-mini",
    created_at: minutesAgo(130),
    updated_at: minutesAgo(126),
    duration_seconds: 231,
    // Timed out before the model reported usage: the backend stores 0.
    total_tokens: 0,
    message_count: 6,
    cost: 0.0381,
    error: "Sandbox timed out after 900 seconds while running the build.",
  },
  {
    // Started a minute ago; the model has not picked a tool yet.
    run_id: "run-0008",
    thread_id: "thread-0008",
    thread_title: "Check the Pro Fence proposal against the brief",
    assistant_id: "dillon-critic",
    status: "pending",
    model_name: "claude-sonnet",
    created_at: minutesAgo(1),
    updated_at: minutesAgo(1),
    duration_seconds: null,
    total_tokens: 0,
    message_count: 1,
    cost: null,
    error: null,
  },
  {
    run_id: "run-0004",
    thread_id: "thread-0004",
    thread_title: "Weekly reliability audit",
    assistant_id: "dillon-reliability",
    status: "success",
    model_name: "gpt-5-mini",
    created_at: minutesAgo(600),
    updated_at: minutesAgo(596),
    duration_seconds: 196,
    total_tokens: 8_811,
    message_count: 5,
    cost: 0.0122,
    error: null,
  },
  // Real prompts often share an opening. These three only differ after the
  // first ~40 characters, which is what backlog item 2 is about.
  ...[
    [
      "run-0005",
      "thread-0005",
      "Pull the September leads for Omega Landscaping and split them by campaign source",
      780,
    ],
    [
      "run-0006",
      "thread-0006",
      "Pull the September leads for Omega Landscaping and flag the calls that never booked",
      1_500,
    ],
    [
      "run-0007",
      "thread-0007",
      "Pull the September leads for Kimberly James Bridal and match them to appointments",
      2_900,
    ],
  ].map(([run_id, thread_id, thread_title, minutes]) => ({
    run_id: run_id as string,
    thread_id: thread_id as string,
    thread_title: thread_title as string,
    assistant_id: "dillon-intelligence",
    status: "success",
    model_name: "claude-sonnet",
    created_at: minutesAgo(minutes as number),
    updated_at: minutesAgo((minutes as number) - 4),
    duration_seconds: 240,
    total_tokens: 22_310,
    message_count: 8,
    cost: 0.21,
    error: null,
  })),
];

const THREAD_MESSAGES = [
  {
    type: "human",
    id: "design-human-1",
    content: [
      {
        type: "text",
        text: "Pull September leads for Omega Landscaping and tell me which campaigns actually converted.",
      },
    ],
  },
  {
    type: "ai",
    id: "design-ai-1",
    content: [
      "## September lead review",
      "",
      "Omega logged **41 form leads** and **17 calls** in September. Only the branded search campaign converted leads into booked estimates at a useful rate.",
      "",
      "### What converted",
      "",
      "1. **Branded search**: 22 leads, 11 booked estimates (50%).",
      "2. **Local services ads**: 19 leads, 4 booked estimates (21%).",
      "3. **Performance Max**: 17 leads, 1 booked estimate. Most were out of the service area.",
      "",
      "> Performance Max spent 38% of budget for 6% of booked work.",
      "",
      "Next step: move the Performance Max budget into branded search and add a service-area exclusion list. The raw export is in `omega-sept-leads.csv`.",
    ].join("\n"),
  },
];

const THREADS = [
  {
    thread_id: MOCK_THREAD_ID,
    title: "Omega Landscaping September lead review",
    updated_at: minutesAgo(1),
    messages: THREAD_MESSAGES,
  },
  {
    thread_id: "00000000-0000-0000-0000-000000000002",
    title: "Draft the Q4 paid search budget memo",
    updated_at: minutesAgo(47),
  },
  {
    thread_id: "00000000-0000-0000-0000-000000000003",
    title: "Rebuild the Bridge directory search page",
    updated_at: minutesAgo(126),
    metadata: { deerflow_project_id: PROJECT_ID },
  },
  {
    thread_id: "00000000-0000-0000-0000-000000000004",
    title: "Weekly reliability audit",
    updated_at: minutesAgo(600),
  },
  {
    thread_id: "00000000-0000-0000-0000-000000000005",
    title:
      "Pull the September leads for Omega Landscaping and split them by campaign source",
    updated_at: minutesAgo(776),
  },
  {
    thread_id: "00000000-0000-0000-0000-000000000006",
    title:
      "Pull the September leads for Omega Landscaping and flag the calls that never booked",
    updated_at: minutesAgo(1_496),
  },
  {
    thread_id: "00000000-0000-0000-0000-000000000007",
    title: "Can you look at this again",
    updated_at: minutesAgo(2_896),
    metadata: { deerflow_project_id: PROJECT_ID },
  },
];

const SCHEDULED_TASKS = [
  {
    id: "task-weekly-report",
    thread_id: null,
    context_mode: "fresh_thread_per_run" as const,
    assistant_id: "omega-reporting",
    title: "Omega Monday performance summary",
    prompt:
      "Summarize last week's leads, spend and booked estimates for Omega Landscaping.",
    schedule_type: "cron" as const,
    schedule_spec: { cron: "0 8 * * 1" },
    timezone: "America/New_York",
    status: "enabled" as const,
    next_run_at: "2026-09-28T12:00:00Z",
    last_run_at: "2026-09-21T12:00:00Z",
    last_run_id: "run-0100",
    last_error: null,
    run_count: 12,
    created_at: "2026-06-01T12:00:00Z",
    updated_at: "2026-09-21T12:04:00Z",
  },
  {
    id: "task-reliability",
    thread_id: null,
    context_mode: "fresh_thread_per_run" as const,
    assistant_id: null,
    title: "Nightly reliability audit",
    prompt: "Check yesterday's scheduled runs for missing artifacts.",
    schedule_type: "interval" as const,
    schedule_spec: { every_seconds: 86_400 },
    timezone: "America/New_York",
    status: "paused" as const,
    next_run_at: null,
    last_run_at: "2026-09-20T04:00:00Z",
    last_run_id: "run-0101",
    last_error: "The gateway restarted during the run.",
    run_count: 30,
    created_at: "2026-05-01T12:00:00Z",
    updated_at: "2026-09-20T04:03:00Z",
  },
];

async function mockDesignAPI(page: Page, { empty = false } = {}) {
  // Anything the fixtures below do not answer resolves to an empty 404 rather
  // than hanging on a gateway that is not running. Registered first so every
  // specific route below takes precedence.
  await page.route("**/api/**", (route) => {
    if (process.env.DESIGN_SHOTS_DEBUG === "1") {
      console.warn("[design-shots] unmocked", route.request().url());
    }
    return route.fulfill({ status: 404, json: { detail: "Not mocked" } });
  });
  mockLangGraphAPI(page, {
    threads: empty ? [] : THREADS,
    agents: AGENTS,
    scheduledTasks: empty ? [] : SCHEDULED_TASKS,
    projects: [
      {
        id: PROJECT_ID,
        name: "Bridge directory relaunch",
        instructions:
          "Tori's cannabis-industry directory. Keep search fast and listings accurate.",
      },
    ],
  });
  await page.route("**/api/models", (route) =>
    route.fulfill({ json: { models: MODELS, token_usage: { enabled: true } } }),
  );
  await page.route("**/api/subagents", (route) =>
    route.fulfill({ json: { subagents: SUBAGENTS } }),
  );
  await page.route("**/api/v1/auth/preferences", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({
          json: {
            notification_enabled: true,
            model_name: null,
            mode: null,
            reasoning_effort: null,
          },
        })
      : route.fulfill({ status: 204 }),
  );
  await page.route("**/api/workspaces", (route) =>
    route.fulfill({
      json: {
        workspaces: [{ id: "momentum", name: "Momentum", role: "owner" }],
        active_workspace_id: "momentum",
      },
    }),
  );
  await page.route("**/api/console/stats", (route) =>
    route.fulfill({
      json: empty
        ? {
            total_runs: 0,
            active_runs: 0,
            failed_runs: 0,
            total_threads: 0,
            total_agents: AGENTS.length,
            total_tokens: 0,
            total_cost: null,
            currency: null,
          }
        : {
            total_runs: 128,
            active_runs: 1,
            failed_runs: 3,
            total_threads: 46,
            total_agents: AGENTS.length,
            total_tokens: 2_418_330,
            total_cost: 18.42,
            currency: "USD",
          },
    }),
  );
  await page.route(/\/api\/console\/runs(\?|$)/, (route) =>
    route.fulfill({ json: { runs: empty ? [] : RUNS, has_more: false } }),
  );
  await page.route(/\/api\/console\/usage(\?|$)/, (route) =>
    route.fulfill({
      json: {
        days: Array.from({ length: 14 }, (_, index) => ({
          date: `2026-09-${String(11 + index).padStart(2, "0")}`,
          total_tokens: empty ? 0 : 60_000 + ((index * 37_000) % 140_000),
          input_tokens: 0,
          output_tokens: 0,
          runs: empty ? 0 : 4 + (index % 6),
          cost: empty ? 0 : 0.6 + (index % 5) * 0.21,
        })),
        by_model: empty
          ? {}
          : {
              "claude-sonnet": {
                tokens: 1_902_110,
                runs: 88,
                cost: 16.9,
                input_tokens: 1_402_110,
                cache_read_tokens: 380_000,
              },
              "gpt-5-mini": {
                tokens: 516_220,
                runs: 40,
                cost: null,
                input_tokens: 400_000,
                cache_read_tokens: 0,
              },
            },
        total_tokens: empty ? 0 : 2_418_330,
        total_runs: empty ? 0 : 128,
        total_cost: empty ? null : 18.42,
        currency: empty ? null : "USD",
      },
    }),
  );
  await page.route(/\/api\/console\/usage-ledger(\?|$)/, (route) =>
    route.fulfill({ json: { attempts: [], has_more: false } }),
  );
  await page.route(/\/api\/clients(\?|$)/, (route) =>
    route.fulfill({
      json: {
        clients: empty
          ? []
          : [
              {
                id: "client-omega",
                display_name: "Omega Landscaping",
                aliases: ["Omega"],
                status: "active",
                email_domains: ["omegalandscaping.com"],
                slack_channel_ids: [],
                registry_id: "omega",
                notes: "Priority conversion lane.",
                created_at: "2026-03-01T12:00:00Z",
                updated_at: "2026-09-20T12:00:00Z",
                assignments: [
                  {
                    user_id: "default",
                    role: "account_manager",
                    created_at: "2026-03-01T12:00:00Z",
                    updated_at: "2026-03-01T12:00:00Z",
                  },
                ],
                project_count: 2,
              },
              {
                id: "client-bridge",
                display_name: "Bridge Software Development",
                aliases: [],
                status: "prospect",
                email_domains: [],
                slack_channel_ids: [],
                registry_id: null,
                notes: "",
                created_at: "2026-08-12T12:00:00Z",
                updated_at: "2026-09-18T12:00:00Z",
                assignments: [],
                project_count: 1,
              },
            ],
      },
    }),
  );
  await page.route("**/api/fleet/templates", (route) =>
    route.fulfill({
      json: {
        templates: [
          {
            id: "weekly-report",
            version: "1.2.0",
            name: "Weekly client report",
            description: "Monday summary of leads, spend and booked work.",
            model: "claude-sonnet",
            skills: ["data-analysis"],
            tool_groups: ["web"],
            mcp_plugins: [],
            schedule: { cron: "0 8 * * 1", timezone: "America/New_York" },
            acceptance_criteria: ["Every number cites its source export."],
          },
        ],
      },
    }),
  );
  await page.route(/\/api\/clients\/[^/]+\/agents$/, (route) =>
    route.fulfill({ json: { agents: [] } }),
  );
  await page.route(/\/api\/projects\/[^/]+\/documents(\?|$)/, (route) =>
    route.fulfill({ json: { documents: [], has_more: false } }),
  );
}

// A thread whose backend usage was recorded, with a known context window.
const RECORDED_THREAD_USAGE = {
  total_tokens: 48_210,
  total_input_tokens: 41_380,
  total_output_tokens: 6_830,
  total_runs: 3,
  by_model: {},
  by_caller: { lead_agent: 48_210, subagent: 0, middleware: 0 },
  context_usage: {
    token_count: 72_800,
    max_context_tokens: 200_000,
    percentage: 36.4,
  },
};

type Surface = {
  name: string;
  path: string;
  empty?: boolean;
  /** Answer the thread token-usage read with recorded usage. */
  recordedUsage?: boolean;
  /** Extra captures after scrolling the main scroller by ~a screen. */
  scrolls?: number;
  prepare?: (page: Page) => Promise<void>;
};

const SIGNED_IN: Surface[] = [
  { name: "workspace-home", path: "/workspace/chats/new" },
  { name: "chats-empty", path: "/workspace/chats", empty: true },
  { name: "chats-list", path: "/workspace/chats" },
  { name: "chat-thread", path: `/workspace/chats/${MOCK_THREAD_ID}` },
  {
    // The recent-chats rows below the fold, with one row keyboard-focused so
    // the full-title-on-focus behaviour shows up in the capture.
    name: "sidebar-recent-chats",
    path: `/workspace/chats/${MOCK_THREAD_ID}`,
    prepare: async (page) => {
      await page.evaluate(() => {
        const content = document.querySelector('[data-sidebar="content"]');
        if (content) content.scrollTop = content.scrollHeight;
      });
      const row = page.getByTitle(
        "Pull the September leads for Omega Landscaping and flag the calls that never booked",
      );
      if (await row.isVisible()) {
        await row.focus();
        await page.keyboard.press("Shift+Tab");
        await page.keyboard.press("Tab");
      }
    },
  },
  {
    // The header usage menu opened on a thread with no recorded usage.
    name: "chat-usage-missing",
    path: `/workspace/chats/${MOCK_THREAD_ID}`,
    prepare: openUsageMenu,
  },
  {
    // The same menu on a thread with recorded usage and a context reading.
    name: "chat-usage-recorded",
    path: `/workspace/chats/${MOCK_THREAD_ID}`,
    recordedUsage: true,
    prepare: openUsageMenu,
  },
  { name: "command-center", path: "/workspace/command-center", scrolls: 2 },
  {
    // The agent team, scrolled into view: one avatar per recorded run state
    // (running lead, thinking Critic, done, failed Builder, idle).
    name: "agent-team",
    path: "/workspace/command-center",
    prepare: async (page) => {
      const team = page.getByRole("group", { name: /Specialist definitions/ });
      await expect(team).toBeVisible();
      await page
        .getByRole("link", { name: "Open lead agent conversation" })
        .evaluate((node) =>
          node.parentElement?.scrollIntoView({ block: "start" }),
        );
    },
  },
  {
    name: "command-center-empty",
    path: "/workspace/command-center",
    empty: true,
    scrolls: 1,
  },
  { name: "agents", path: "/workspace/agents" },
  {
    name: "agent-settings",
    path: "/workspace/agents",
    prepare: async (page) => {
      await page.getByTitle("Agent settings").first().click();
      await expect(page.getByRole("dialog")).toBeVisible();
    },
  },
  { name: "project", path: `/workspace/projects/${PROJECT_ID}` },
  { name: "scheduled-tasks", path: "/workspace/scheduled-tasks", scrolls: 1 },
  {
    name: "scheduled-tasks-empty",
    path: "/workspace/scheduled-tasks",
    empty: true,
    scrolls: 1,
  },
  { name: "capabilities", path: "/workspace/capabilities", scrolls: 1 },
  {
    name: "settings",
    path: "/workspace/chats/new?settings=appearance",
    prepare: (page) => expect(page.getByRole("dialog")).toBeVisible(),
  },
  {
    name: "settings-security",
    path: "/workspace/chats/new?settings=security",
    prepare: (page) => expect(page.getByRole("dialog")).toBeVisible(),
  },
  {
    name: "client-spaces",
    path: "/workspace/command-center",
    scrolls: 1,
    prepare: async (page) => {
      await page.getByRole("button", { name: "Client Spaces" }).click();
    },
  },
  { name: "daily", path: "/daily", scrolls: 2 },
];

async function openUsageMenu(page: Page) {
  await page
    .getByRole("button", { name: /tokens/i })
    .first()
    .click();
  await expect(page.getByRole("menu")).toBeVisible();
}

const SIGNED_OUT: Surface[] = [
  { name: "landing", path: "/", scrolls: 3 },
  {
    name: "invite",
    path: "/invite#token=design-review",
    prepare: async (page) => {
      await expect(
        page.getByText("Momentum", { exact: false }).first(),
      ).toBeVisible();
    },
  },
];

async function capture(
  page: Page,
  surface: Surface,
  viewport: (typeof VIEWPORTS)[number],
  baseURL?: string,
) {
  await page.setViewportSize({
    width: viewport.width,
    height: viewport.height,
  });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(baseURL ? new URL(surface.path, baseURL).href : surface.path);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await surface.prepare?.(page);
  // Let fonts, lazy panels and query refetches settle before the capture.
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(600);
  mkdirSync(outDir, { recursive: true });
  const file = path.join(outDir, `${surface.name}-${viewport.name}.png`);
  await page.screenshot({ path: file });
  // App pages scroll inside a container, so a fullPage capture would only
  // repeat the viewport: scroll the largest scroller instead.
  for (let index = 1; index <= (surface.scrolls ?? 0); index++) {
    const moved = await page.evaluate(() => {
      const candidates = [
        document.scrollingElement,
        ...document.querySelectorAll<HTMLElement>("*"),
      ].filter(
        (element): element is Element =>
          element !== null &&
          element.scrollHeight > element.clientHeight + 40 &&
          (element === document.scrollingElement ||
            /auto|scroll/.test(getComputedStyle(element).overflowY)),
      );
      const scroller = candidates.sort(
        (a, b) =>
          b.clientHeight * b.clientWidth - a.clientHeight * a.clientWidth,
      )[0];
      if (!scroller) return false;
      const before = scroller.scrollTop;
      scroller.scrollTop += scroller.clientHeight * 0.85;
      return scroller.scrollTop > before;
    });
    if (!moved) break;
    await page.waitForTimeout(300);
    await page.screenshot({
      path: path.join(
        outDir,
        `${surface.name}-${viewport.name}-${index + 1}.png`,
      ),
    });
  }
}

test.describe("design surfaces", () => {
  test.skip(!enabled, "Set DESIGN_SHOTS=1 to capture design screenshots.");
  test.describe.configure({ timeout: 60_000 });

  for (const viewport of VIEWPORTS) {
    for (const surface of SIGNED_IN.filter((s) => wanted(s.name))) {
      test(`${surface.name} ${viewport.name}`, async ({ page }) => {
        await mockDesignAPI(page, { empty: surface.empty });
        if (surface.recordedUsage) {
          await page.route("**/api/threads/*/token-usage", (route) =>
            route.fulfill({
              json: { thread_id: MOCK_THREAD_ID, ...RECORDED_THREAD_USAGE },
            }),
          );
        }
        await capture(page, surface, viewport);
      });
    }

    for (const surface of SIGNED_OUT.filter((s) => wanted(s.name))) {
      test(`${surface.name} ${viewport.name}`, async ({ page }) => {
        await page.route("**/api/v1/auth/invitations/inspect", (route) =>
          route.fulfill({
            json: {
              email: "tori@bridgesoftware.dev",
              workspace_name: "Momentum",
              expires_at: "2026-10-01T12:00:00Z",
              requires_login: false,
            },
          }),
        );
        await capture(page, surface, viewport);
      });
    }

    test(`login ${viewport.name}`, async ({ page }) => {
      test.skip(
        !signedOutURL || !wanted("login"),
        "Set DESIGN_SIGNED_OUT_URL for /login.",
      );
      await page.route("**/api/v1/auth/providers", (route) =>
        route.fulfill({
          json: {
            providers: [{ id: "google", display_name: "Google", type: "oidc" }],
          },
        }),
      );
      await capture(
        page,
        { name: "login", path: "/login" },
        viewport,
        signedOutURL,
      );
    });
  }
});
