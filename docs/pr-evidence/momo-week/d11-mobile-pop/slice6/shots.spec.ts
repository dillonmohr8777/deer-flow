import { test } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

test.use({ launchOptions: { executablePath: "/opt/pw-browsers/chromium" } });

const OUT = process.env.SHOT_DIR ?? "shots";
const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";

const THREAD = {
  thread_id: MOCK_THREAD_ID,
  title: "Acme spring campaign plan",
  updated_at: "2026-09-29T09:00:00Z",
  messages: [
    {
      type: "human",
      id: "h1",
      content: [
        {
          type: "text",
          text: "Plan the Acme Landscaping spring campaign. Budget is $4,000 a month and they want more lawn-care leads in Chester County.",
        },
      ],
    },
    {
      type: "ai",
      id: "a1",
      content:
        "Here is a first plan for **Acme Landscaping**.\n\n## Goal\nMore booked lawn-care estimates in Chester County, March to May.\n\n## Split\n- **Search ads, $2,400:** lawn care, aeration, spring cleanup near West Chester and Downingtown.\n- **Local service ads, $1,000:** pay per lead, verified reviews up top.\n- **Retargeting, $600:** site visitors who priced a service but did not book.\n\n## First week\n1. Audit the Google Business Profile photos and hours.\n2. Build one landing page per service.\n3. Set call tracking so every lead can be named in the report.\n\nI have not checked last year's numbers, so the split is inferred, not observed.",
    },
    {
      type: "human",
      id: "h2",
      content: [{ type: "text", text: "Good. Draft the client email." }],
    },
    {
      type: "ai",
      id: "a2",
      content:
        "Draft for review:\n\n> Hi Maria, here is the spring plan in one page. We would put most of the budget into search ads for lawn care and spring cleanup, and track every call so the monthly report names each lead. Can we get 20 minutes Thursday to walk through it?\n\nSay the word and I will adjust the tone.",
    },
  ],
};

for (const [w, h, mobile] of [
  [390, 844, true],
  [430, 932, true],
  [1440, 900, false],
] as const) {
  test.describe(`${w}`, () => {
    test.use({
      viewport: { width: w, height: h },
      ...(mobile ? { userAgent: IPHONE, isMobile: true, hasTouch: true } : {}),
    });
    test(`welcome ${w}`, async ({ page }) => {
      mockLangGraphAPI(page, { threads: [THREAD] as never });
      await page.goto("/workspace/chats/new");
      await page.getByRole("textbox").first().waitFor();
      await page.waitForTimeout(1500);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      console.log(`welcome ${w} overflow=${overflow}`);
      await page.screenshot({ path: `${OUT}/welcome-${w}.png` });
    });
    test(`thread ${w}`, async ({ page }) => {
      mockLangGraphAPI(page, { threads: [THREAD] as never });
      await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
      await page.getByText("Draft for review").waitFor({ timeout: 20_000 });
      await page.waitForTimeout(1500);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      console.log(`thread ${w} overflow=${overflow}`);
      await page.screenshot({ path: `${OUT}/thread-${w}.png` });
      await page.getByText("Plan the Acme").first().scrollIntoViewIfNeeded();
      await page.waitForTimeout(300);
      await page.screenshot({ path: `${OUT}/thread-${w}-top.png` });
    });
  });
}
