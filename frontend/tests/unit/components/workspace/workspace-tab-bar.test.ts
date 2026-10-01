import { describe, expect, it } from "@rstest/core";

import {
  claimBottomEdge,
  isBottomEdgeClaimed,
  isConversationPath,
} from "@/components/workspace/workspace-tab-bar";

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

describe("claimBottomEdge", () => {
  it("steps the bar aside while any composer holds the edge, and only then", () => {
    expect(isBottomEdgeClaimed()).toBe(false);
    const releaseA = claimBottomEdge();
    const releaseB = claimBottomEdge();
    expect(isBottomEdgeClaimed()).toBe(true);
    releaseA();
    // A second release of the same claim must not free the other one.
    releaseA();
    expect(isBottomEdgeClaimed()).toBe(true);
    releaseB();
    expect(isBottomEdgeClaimed()).toBe(false);
  });
});
