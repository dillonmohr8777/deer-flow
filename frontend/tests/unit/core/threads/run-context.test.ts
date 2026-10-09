import { describe, expect, it } from "@rstest/core";

import type { LocalSettings } from "@/core/settings";
import { getResolvedMode } from "@/core/settings/local";
import { buildRunContext } from "@/core/threads/hooks";

const settings = {
  mode: "pro",
  model_name: "gemma4",
  reasoning_effort: undefined,
} as unknown as LocalSettings["context"];

describe("buildRunContext", () => {
  it.each([
    ["flash", false, false, false, undefined],
    ["pro", true, true, false, "medium"],
    ["ultra", true, true, true, "high"],
  ] as const)(
    "%s preserves its distinct runtime options on a non-thinking model",
    (mode, thinking, planning, subagents, effort) => {
      const context = buildRunContext({
        settings: { ...settings, mode: getResolvedMode(mode, false) },
        threadId: "mode-test",
      });
      expect(context).toMatchObject({
        mode,
        thinking_enabled: thinking,
        is_plan_mode: planning,
        subagent_enabled: subagents,
        reasoning_effort: effort,
      });
    },
  );

  it.each(["minimal", "low", "medium", "high"] as const)(
    "preserves an explicit %s reasoning effort for the backend capability check",
    (reasoning_effort) => {
      expect(
        buildRunContext({
          settings: { ...settings, mode: "ultra", reasoning_effort },
          threadId: "effort-test",
        }).reasoning_effort,
      ).toBe(reasoning_effort);
    },
  );

  it("sends attached references as a plain string[] under context.conversation_references", () => {
    const context = buildRunContext({
      settings,
      threadId: "t-1",
      extraContext: { agent_name: "writer" },
      conversationReferences: ["source-a", "source-b"],
    });
    expect(context.conversation_references).toEqual(["source-a", "source-b"]);
    expect(context.agent_name).toBe("writer");
    expect(context.thread_id).toBe("t-1");
    expect(context.is_plan_mode).toBe(true);
  });

  it("omits the key when nothing is attached, including on the replay path", () => {
    expect(
      "conversation_references" in
        buildRunContext({ settings, threadId: "t-1" }),
    ).toBe(false);
    expect(
      "conversation_references" in
        buildRunContext({
          settings,
          threadId: "t-1",
          conversationReferences: [],
        }),
    ).toBe(false);
  });

  it("never forwards a stray conversation_references key from local settings", () => {
    const stale = {
      ...settings,
      conversation_references: ["stale-source"],
    } as unknown as LocalSettings["context"];
    expect(
      "conversation_references" in
        buildRunContext({ settings: stale, threadId: "t-1" }),
    ).toBe(false);
    expect(
      buildRunContext({
        settings: stale,
        threadId: "t-1",
        conversationReferences: ["source-a"],
      }).conversation_references,
    ).toEqual(["source-a"]);
  });

  it("forwards the account's experience_mode preference on every run", () => {
    const context = buildRunContext({
      settings: { ...settings, experience_mode: "easy" },
      threadId: "t-1",
    });
    expect(context.experience_mode).toBe("easy");
  });

  it("omits experience_mode when the account has not chosen one (medium behaviour)", () => {
    expect(
      "experience_mode" in buildRunContext({ settings, threadId: "t-1" }),
    ).toBe(false);
  });

  it("copies the list so later mutation of the caller's array cannot change the request", () => {
    const references = ["source-a"];
    const context = buildRunContext({
      settings,
      threadId: "t-1",
      conversationReferences: references,
    });
    references.push("source-b");
    expect(context.conversation_references).toEqual(["source-a"]);
  });
});
