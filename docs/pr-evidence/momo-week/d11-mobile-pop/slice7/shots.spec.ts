// Slice 7 evidence: agent identity on assistant turns. Run from frontend/
// with this file copied into tests/e2e and SHOT_DIR set.
import { expect, test } from "@playwright/test";

import { MOCK_THREAD_ID, mockLangGraphAPI } from "./utils/mock-api";

const OUT = process.env.SHOT_DIR ?? "shots";
const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";
const AGENTS = [
  { name: "dillon-growth", display_name: "Growth", description: "Plans paid and organic growth for each client.", model: "claude-sonnet", tool_groups: [], skills: [] },
];
const THREAD = {
  thread_id: MOCK_THREAD_ID,
  title: "October growth memo for Fresh Pantry",
  messages: [
    { type: "human", id: "h1", content: [{ type: "text", text: "Draft the October growth memo for Fresh Pantry." }] },
    { type: "ai", id: "a1", content: "Here is the October memo draft.\n\nOrganic sessions rose 14% on the new recipe pages, while paid search held flat at the same spend. I would move 10% of the search budget to the recipe landing pages and test two new headlines.\n\nI have not checked the September invoice, so the spend figure is inferred from the plan." },
    { type: "human", id: "h2", content: [{ type: "text", text: "Shorter, and lead with the ask." }] },
    { type: "ai", id: "a2", content: "Ask: move 10% of search budget to the recipe pages.\n\nWhy: organic sessions there rose 14% while paid search held flat." },
  ],
};

for (const [w, h, mobile] of [[390, 844, true], [430, 932, true], [1440, 900, false]] as const) {
  test.describe(`${w}`, () => {
    test.use({ viewport: { width: w, height: h }, ...(mobile ? { userAgent: IPHONE, isMobile: true, hasTouch: true } : {}) });
    test(`agent chat ${w}`, async ({ page }) => {
      mockLangGraphAPI(page, { agents: AGENTS, threads: [THREAD] });
      await page.goto(`/workspace/agents/dillon-growth/chats/${MOCK_THREAD_ID}`);
      await page.getByText("Ask: move 10%").waitFor();
      await page.waitForTimeout(1200);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow).toBeLessThanOrEqual(0);
      await page.screenshot({ path: `${OUT}/agent-chat-${w}.png` });
      await page.evaluate(() => {
        const el = document.querySelector("[data-testid='main-message-list'] [data-assistant-turn]");
        el?.scrollIntoView({ block: "start" });
      });
      await page.waitForTimeout(300);
      await page.screenshot({ path: `${OUT}/agent-chat-${w}-top.png` });
    });
  });
}
