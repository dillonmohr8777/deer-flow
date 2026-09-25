import { describe, expect, it } from "@rstest/core";

import {
  canApprove,
  canDraft,
  canSendReply,
  latestMomoDraft,
  sortThreadsByUpdated,
  statusTone,
} from "@/components/workspace/board/board-data";
import type { BoardMessage, BoardThread } from "@/core/board";

function thread(patch: Partial<BoardThread>): BoardThread {
  return {
    id: "t1",
    client_id: "acme",
    kind: "ticket",
    status: "new",
    subject: "Site is down",
    created_by_user_id: "client-1",
    created_at: "2026-09-20T00:00:00Z",
    updated_at: "2026-09-20T00:00:00Z",
    ...patch,
  };
}

function message(patch: Partial<BoardMessage>): BoardMessage {
  return {
    id: "m1",
    thread_id: "t1",
    author_kind: "client",
    author_user_id: null,
    body: "",
    created_at: "2026-09-20T00:00:00Z",
    ...patch,
  };
}

describe("board data", () => {
  it("mirrors deerflow.board.workflow's draft/approve/reply gates", () => {
    expect(canDraft("new")).toBe(true);
    expect(canDraft("triaged")).toBe(true);
    expect(canDraft("drafted")).toBe(false);
    expect(canDraft("approved")).toBe(false);

    expect(canApprove("drafted")).toBe(true);
    expect(canApprove("new")).toBe(false);
    expect(canApprove("approved")).toBe(false);

    expect(canSendReply("approved")).toBe(true);
    expect(canSendReply("drafted")).toBe(false);
    expect(canSendReply("replied")).toBe(false);
  });

  it("gives each status a tone", () => {
    expect(statusTone("new")).toBe("attention");
    expect(statusTone("triaged")).toBe("attention");
    expect(statusTone("drafted")).toBe("attention");
    expect(statusTone("approved")).toBe("active");
    expect(statusTone("replied")).toBe("ok");
    expect(statusTone("closed")).toBe("idle");
  });

  it("sorts threads newest-updated first", () => {
    const older = thread({ id: "a", updated_at: "2026-09-20T00:00:00Z" });
    const newer = thread({ id: "b", updated_at: "2026-09-24T00:00:00Z" });
    const middle = thread({ id: "c", updated_at: "2026-09-22T00:00:00Z" });
    expect(
      sortThreadsByUpdated([older, newer, middle]).map((t) => t.id),
    ).toEqual(["b", "c", "a"]);
  });

  it("finds Momo's most recent draft, ignoring other authors", () => {
    const clientMsg = message({
      id: "c1",
      author_kind: "client",
      body: "help",
      created_at: "2026-09-20T00:00:00Z",
    });
    const olderDraft = message({
      id: "m1",
      author_kind: "momo",
      body: "first draft",
      created_at: "2026-09-20T01:00:00Z",
    });
    const newerDraft = message({
      id: "m2",
      author_kind: "momo",
      body: "second draft",
      created_at: "2026-09-20T02:00:00Z",
    });
    expect(latestMomoDraft([clientMsg, olderDraft, newerDraft])?.body).toBe(
      "second draft",
    );
    expect(latestMomoDraft([clientMsg])).toBeUndefined();
  });
});
