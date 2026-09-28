import { describe, expect, it } from "@rstest/core";

import {
  authorLabel,
  canApprove,
  canDraft,
  canSendReply,
  conversationMessages,
  draftOnSheet,
  isDecided,
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

  it("stamps only recorded decisions", () => {
    expect(isDecided("new")).toBe(false);
    expect(isDecided("triaged")).toBe(false);
    expect(isDecided("drafted")).toBe(false);
    expect(isDecided("approved")).toBe(true);
    expect(isDecided("replied")).toBe(true);
    expect(isDecided("closed")).toBe(true);
  });

  describe("conversation", () => {
    const ask = message({
      id: "c1",
      author_kind: "client",
      body: "Site is down",
      created_at: "2026-09-20T00:00:00Z",
    });
    const oldDraft = message({
      id: "m1",
      author_kind: "momo",
      body: "first try",
      created_at: "2026-09-20T01:00:00Z",
    });
    const draft = message({
      id: "m2",
      author_kind: "momo",
      body: "Restoring it now.",
      created_at: "2026-09-20T02:00:00Z",
    });
    const ids = (list: BoardMessage[]) => list.map((m) => m.id);

    it("leaves the latest draft to the sheet while it is under review", () => {
      expect(draftOnSheet("drafted")).toBe(true);
      expect(draftOnSheet("approved")).toBe(true);
      expect(draftOnSheet("triaged")).toBe(false);
      expect(ids(conversationMessages([ask, draft], "drafted"))).toEqual([
        "c1",
      ]);
      expect(ids(conversationMessages([ask, draft], "approved"))).toEqual([
        "c1",
      ]);
      // An older draft that was superseded still reads as history.
      expect(
        ids(conversationMessages([ask, oldDraft, draft], "drafted")),
      ).toEqual(["c1", "m1"]);
    });

    it("keeps a draft sent back for a redraft in the conversation", () => {
      expect(ids(conversationMessages([ask, draft], "triaged"))).toEqual([
        "c1",
        "m2",
      ]);
    });

    it("does not repeat a draft that went out word for word", () => {
      const reply = message({
        id: "o1",
        author_kind: "owner",
        body: "Restoring it now.",
        created_at: "2026-09-20T03:00:00Z",
      });
      expect(ids(conversationMessages([ask, draft, reply], "replied"))).toEqual(
        ["c1", "o1"],
      );
      const edited = { ...reply, body: "Restoring it now, sorry." };
      expect(
        ids(conversationMessages([ask, draft, edited], "replied")),
      ).toEqual(["c1", "m2", "o1"]);
    });
  });

  it("names authors in words, never the raw enum", () => {
    expect(authorLabel("client", "Acme Landscaping")).toBe("Acme Landscaping");
    expect(authorLabel("owner", "Acme Landscaping")).toBe("Momentum");
    expect(authorLabel("momo", "Acme Landscaping")).toBe("Momo, draft");
  });
});
