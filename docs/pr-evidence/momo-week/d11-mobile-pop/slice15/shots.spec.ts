import { test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.setTimeout(45_000);
test.use({ launchOptions: { executablePath: "/opt/pw-browsers/chromium" } });

const OUT = process.env.SHOT_DIR ?? "shots";
const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";

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

    test(`chat-new ${w}`, async ({ page }) => {
      mockLangGraphAPI(page, { threads: [] });
      await page.goto("/workspace/chats/new");
      await page.waitForTimeout(2500);
      // The composer: its placeholder words and colour, and how many rows
      // its footer takes (the send button's row against the tools' row).
      const m = await page.evaluate(() => {
        const ta = document.querySelector("textarea")!;
        const form = ta.closest("form")!.getBoundingClientRect();
        const send = document
          .querySelector('button[aria-label="Send"], button[type="submit"]')
          ?.getBoundingClientRect();
        const tool = document
          .querySelector("[data-chat-starters]")
          ?.getBoundingClientRect();
        return {
          overflow: document.documentElement.scrollWidth - window.innerWidth,
          placeholder: ta.placeholder,
          placeholderColor: getComputedStyle(ta, "::placeholder").color,
          composer: `${Math.round(form.top)}..${Math.round(form.bottom)} (${Math.round(form.height)}h)`,
          sendTop: Math.round(send?.top ?? -1),
          startersTop: Math.round(tool?.top ?? -1),
        };
      });
      console.log(`chat-new ${w} ${JSON.stringify(m)}`);
      await page.screenshot({ path: `${OUT}/chat-new-${w}.png` });
    });

    test(`chat-thread ${w}`, async ({ page }) => {
      const id = "00000000-0000-4000-8000-000000000015";
      mockLangGraphAPI(page, {
        threads: [
          {
            thread_id: id,
            title: "Omega spring report",
            messages: [
              {
                type: "human",
                id: "h1",
                content: [{ type: "text", text: "Draft the spring report." }],
              },
              {
                type: "ai",
                id: "a1",
                content: [
                  { type: "text", text: "Draft ready: three wins, one gap." },
                ],
              },
            ],
          },
        ],
      });
      await page.goto(`/workspace/chats/${id}`);
      await page.waitForTimeout(2500);
      const m = await page.evaluate(() => {
        const ta = document.querySelector("textarea");
        return {
          overflow: document.documentElement.scrollWidth - window.innerWidth,
          placeholder: ta?.placeholder,
        };
      });
      console.log(`chat-thread ${w} ${JSON.stringify(m)}`);
      await page.screenshot({ path: `${OUT}/chat-thread-${w}.png` });
    });
  });
}
