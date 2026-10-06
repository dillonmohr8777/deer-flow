import { describe, expect, test } from "@rstest/core";

import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import { findSuggestionTemplatePlaceholder } from "@/core/suggestions/placeholders";

describe("empty-thread starter prompts", () => {
  test("each carries a placeholder the composer selects and guards", () => {
    for (const locale of [enUS, zhCN]) {
      expect(locale.inputBox.starters).toHaveLength(4);
      for (const starter of locale.inputBox.starters) {
        expect(
          findSuggestionTemplatePlaceholder(starter.prompt),
        ).not.toBeNull();
      }
    }
  });

  test("finds the client placeholder in both languages", () => {
    expect(
      findSuggestionTemplatePlaceholder("Plan the delivery for [client]."),
    ).toEqual({ start: 22, end: 30 });
    expect(findSuggestionTemplatePlaceholder("规划 [客户] 的交付")).toEqual({
      start: 3,
      end: 7,
    });
  });

  // f159: these starters show on the default new-chat composer, which has
  // no `tool_groups` and so never loads `draft_board_thread`/`deliberate` --
  // a prompt that promises a board-thread draft would leave the model only
  // able to improvise or falsely claim it drafted one.
  test("never promises a board-thread draft, which the default agent can't make", () => {
    for (const locale of [enUS, zhCN]) {
      for (const starter of locale.inputBox.starters) {
        expect(starter.prompt).not.toContain("board thread");
        expect(starter.prompt).not.toContain("看板帖子");
      }
    }
  });
});

describe("findSuggestionTemplatePlaceholder", () => {
  test("finds Chinese [主题] and returns correct range", () => {
    const result = findSuggestionTemplatePlaceholder(
      "深入浅出的研究一下[主题]，并总结发现。",
    );
    expect(result).toEqual({ start: 9, end: 13 });
  });

  test("finds English [topic] and returns correct range", () => {
    const result = findSuggestionTemplatePlaceholder(
      "Write a blog post about the latest trends on [topic]",
    );
    expect(result).toEqual({ start: 45, end: 52 });
  });

  test("finds Chinese [来源] placeholder", () => {
    const result =
      findSuggestionTemplatePlaceholder("从[来源]收集数据并创建报告。");
    expect(result).not.toBeNull();
  });

  test("finds English [source] placeholder", () => {
    const result = findSuggestionTemplatePlaceholder(
      "Collect data from [source] and create a report.",
    );
    expect(result).not.toBeNull();
  });

  test("returns null for normal text without brackets", () => {
    expect(
      findSuggestionTemplatePlaceholder("研究一下2025年最流行的Python框架"),
    ).toBeNull();
  });

  test("returns null for text with unrelated brackets", () => {
    expect(
      findSuggestionTemplatePlaceholder("check [this link] for details"),
    ).toBeNull();
  });

  test("returns null for empty text", () => {
    expect(findSuggestionTemplatePlaceholder("")).toBeNull();
  });

  test("detects placeholder case-insensitively for English", () => {
    expect(
      findSuggestionTemplatePlaceholder("Research [Topic] deeply"),
    ).not.toBeNull();
    expect(
      findSuggestionTemplatePlaceholder("Research [TOPIC] deeply"),
    ).not.toBeNull();
  });
});
