import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";

import { BoardBody } from "@/components/workspace/board/board";
import type { BoardThread } from "@/core/board";

const mocks = rs.hoisted(() => ({
  threads: [] as BoardThread[],
  draftMutate: rs.fn(),
}));

rs.mock("@/core/clients", () => ({
  useClients: () => ({ data: [] }),
}));

rs.mock("@/core/board", () => ({
  useBoardThreads: () => ({
    data: mocks.threads,
    isLoading: false,
    isError: false,
    error: null,
    refetch: rs.fn(),
  }),
  useBoardThread: (threadId: string | null) => ({
    data: mocks.threads.find((t) => t.id === threadId),
    isLoading: false,
    isError: false,
    error: null,
  }),
  useBoardMessages: () => ({
    data: [],
    isLoading: false,
    isError: false,
    error: null,
  }),
  useDraftBoardReply: () => ({
    mutate: mocks.draftMutate,
    isPending: false,
    isError: false,
    error: null,
  }),
  useApproveBoardReply: () => ({
    mutate: rs.fn(),
    isPending: false,
    isError: false,
    error: null,
  }),
  useSendBoardReply: () => ({
    mutate: rs.fn(),
    isPending: false,
    isError: false,
    error: null,
  }),
}));

function thread(id: string, subject: string, updatedAt: string): BoardThread {
  return {
    id,
    client_id: null,
    kind: "ticket",
    status: "new",
    subject,
    urgency: null,
    summary: null,
    created_by_user_id: null,
    created_at: updatedAt,
    updated_at: updatedAt,
  };
}

beforeEach(() => {
  mocks.threads = [
    thread("t1", "Thread A", "2026-09-20T00:00:00.000Z"),
    thread("t2", "Thread B", "2026-09-19T00:00:00.000Z"),
  ];
  mocks.draftMutate = rs.fn();
});

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
  rs.restoreAllMocks();
});

describe("Board thread detail, switching threads (f5)", () => {
  it("opens mobile detail and restores the selected row on Back", () => {
    const media = window.matchMedia("(max-width: 63.999rem)");
    rs.spyOn(window, "matchMedia").mockReturnValue({ ...media, matches: true });
    render(<BoardBody />);
    const row = screen.getByRole("button", { name: /Thread A/ });
    fireEvent.click(row);
    expect(document.activeElement).toBe(
      screen.getByRole("region", { name: "Board thread detail" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Back to threads" }));
    expect(document.activeElement).toBe(row);
    expect(
      row.closest("[data-mobile-view]")?.getAttribute("data-mobile-view"),
    ).toBe("list");
  });

  it("does not carry a typed draft on thread A over to thread B", () => {
    render(<BoardBody />);
    const board = screen.getByTestId("board");

    fireEvent.click(within(board).getByText("Thread A"));
    const draftOnA =
      screen.getByLabelText<HTMLTextAreaElement>("Draft a reply");
    fireEvent.change(draftOnA, {
      target: { value: "Reply meant for thread A only" },
    });
    expect(draftOnA.value).toBe("Reply meant for thread A only");

    fireEvent.click(within(board).getByText("Thread B"));
    const draftOnB =
      screen.getByLabelText<HTMLTextAreaElement>("Draft a reply");
    expect(draftOnB.value).toBe("");
    expect(draftOnB).not.toBe(draftOnA);

    // The save button is disabled on empty text, so nothing carrying
    // thread A's body can be POSTed to thread B.
    const saveButton = screen.getByRole<HTMLButtonElement>("button", {
      name: "Save draft",
    });
    expect(saveButton.disabled).toBe(true);
    expect(mocks.draftMutate).not.toHaveBeenCalled();
  });
});
