import { test } from "@playwright/test";

import { handleRunStream, mockLangGraphAPI } from "./utils/mock-api";

test.use({ launchOptions: { executablePath: "/opt/pw-browsers/chromium" } });

const OUT = process.env.SHOT_DIR ?? "shots";

// The New agent chat step: name the agent, Continue, and the bootstrap
// conversation opens with its own top bar.
for (const [w, h] of [
  [390, 844],
  [1440, 900],
] as const) {
  test.describe(`${w}x${h}`, () => {
    test.use({ viewport: { width: w, height: h } });
    test(`new agent chat ${w}x${h}`, async ({ page }) => {
      // The thread re-reads its history after each run, so history carries
      // the conversation: the bootstrap turn, then (after Save) a
      // setup_agent tool result that lands the page on its saved state.
      let saved = false;
      const bootstrap = [
        {
          type: "human",
          id: "h-boot",
          content: [
            {
              type: "text",
              text: "The new custom agent name is seo-auditor. Help me design its purpose, behavior, and SOUL.md before saving it.",
            },
          ],
        },
        { type: "ai", id: "a-boot", content: "Hello from DeerFlow!" },
      ];
      const saveTurn = [
        {
          type: "ai",
          id: "a-setup",
          content: "",
          tool_calls: [{ id: "call-setup", name: "setup_agent", args: {} }],
        },
        {
          type: "tool",
          id: "t-setup",
          name: "setup_agent",
          tool_call_id: "call-setup",
          content: "Saved.",
        },
        {
          type: "ai",
          id: "a-done",
          content: "seo-auditor is saved with a first SOUL.md.",
        },
      ];
      const conversation = () =>
        saved ? [...bootstrap, ...saveTurn] : bootstrap;
      mockLangGraphAPI(page, {
        threads: [],
        agents: [{ name: "seo-auditor", description: "Audits SEO" }],
        runStreamHandler: async (route) => {
          saved ||= (route.request().postData() ?? "").includes(
            "save this custom agent now",
          );
          return handleRunStream(route, {}, conversation().slice(0, -1), {
            responseMessage: conversation().at(-1)!,
          });
        },
      });
      await page.route("**/api/langgraph/threads/*/history", (route) =>
        route.fulfill({
          json: [
            {
              values: { title: "New agent", messages: conversation() },
              next: [],
              metadata: {},
              created_at: "2025-01-01T00:00:00Z",
              parent_config: null,
            },
          ],
        }),
      );
      await page.route("**/api/agents/check?*", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ available: true, name: "seo-auditor" }),
        }),
      );
      await page.goto("/workspace/agents/new");
      await page.getByRole("textbox").first().fill("seo-auditor");
      await page.getByRole("button", { name: "Continue" }).click();
      await page.getByText("Hello from DeerFlow!").first().waitFor();
      await page.waitForTimeout(800);
      const facts = await page.evaluate(() => {
        const box = (el: Element | null) => {
          const r = el?.getBoundingClientRect();
          return r
            ? [
                Math.round(r.left),
                Math.round(r.top),
                Math.round(r.width),
                Math.round(r.height),
              ]
            : null;
        };
        const header = document.querySelector("header");
        return {
          overflow: document.documentElement.scrollWidth - window.innerWidth,
          header: box(header),
          h1: box(document.querySelector("h1")),
          h1Font: document.querySelector("h1")
            ? getComputedStyle(document.querySelector("h1")!).fontFamily
            : null,
          buttons: [...(header?.querySelectorAll("a,button") ?? [])].map(
            (b) => [
              b.getAttribute("aria-label") ?? b.textContent?.trim(),
              box(b),
            ],
          ),
        };
      });
      console.log(`${w}x${h} ${JSON.stringify(facts)}`);
      await page.screenshot({ path: `${OUT}/chat-${w}.png` });
      const save = page.getByRole("button", { name: /save agent/i });
      if (await save.isVisible()) {
        await save.click();
        await page
          .getByRole("status")
          .filter({ hasText: "ready for" })
          .waitFor();
        // Let the "Save requested" toast clear so the header shows.
        await page.waitForTimeout(5500);
        await page.screenshot({ path: `${OUT}/chat-saved-${w}.png` });
      }
    });
  });
}
