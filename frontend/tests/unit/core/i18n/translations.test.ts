import { describe, expect, it } from "@rstest/core";

import { loadTranslations } from "@/core/i18n/translations";

describe("core copy loading", () => {
  it("loads only the requested overseas and domestic copy", async () => {
    const [english, chinese] = await Promise.all([
      loadTranslations("en-US"),
      loadTranslations("zh-CN"),
    ]);
    expect(english.inputBox.disclaimer).toBe(
      "Agents can make mistakes. Check the record.",
    );
    expect(chinese.inputBox.disclaimer).toBe("智能体可能会出错，请核查记录。");
    expect(english.channels.descriptions.buzz).toBe(
      "Buzz channels and direct messages through your Momentum agent.",
    );
    expect(chinese.channels.descriptions.buzz).toBe(
      "通过 Momentum 智能体接收 Buzz 频道消息和私聊。",
    );
    expect(chinese.knowledge.scope.title).toBe("知识库范围");
  });
});
