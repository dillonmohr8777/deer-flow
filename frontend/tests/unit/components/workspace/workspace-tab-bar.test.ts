import { describe, expect, it } from "@rstest/core";

import { isConversationPath } from "@/components/workspace/workspace-tab-bar";

describe("isConversationPath", () => {
  it("hides the tab bar inside a conversation, where the composer owns the bottom edge", () => {
    expect(isConversationPath("/workspace/chats/thread-1")).toBe(true);
    expect(isConversationPath("/workspace/agents/growth/chats/thread-1")).toBe(
      true,
    );
  });

  it("keeps it on top-level destinations and the new chat welcome", () => {
    for (const path of [
      "/workspace/chats",
      "/workspace/chats/new",
      "/workspace/agents/growth/chats/new",
      "/workspace/desk",
      "/workspace/board",
      "/workspace/command-center",
    ]) {
      expect(isConversationPath(path)).toBe(false);
    }
  });
});
