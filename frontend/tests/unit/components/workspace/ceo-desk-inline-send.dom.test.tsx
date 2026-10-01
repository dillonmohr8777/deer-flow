import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { CeoDeskBody } from "@/components/workspace/ceo-desk/ceo-desk";
import {
  CEO_NEEDS_MY_YES_QUERY_KEY,
  type BoardDraftAwaitingApproval,
} from "@/core/ceo-desk";

const mocks = rs.hoisted(() => ({
  boardDrafts: [] as BoardDraftAwaitingApproval[],
  approveMutate: rs.fn(),
  sendMutate: rs.fn(),
}));

rs.mock("@/core/ceo-desk", () => ({
  CEO_NEEDS_MY_YES_QUERY_KEY: ["ceo", "needs-my-yes"],
  CEO_DIGEST_QUERY_KEY: ["ceo", "digest"],
  useDailyDigest: () => ({
    data: null,
    isLoading: false,
    isError: false,
    error: null,
  }),
  useNeedsMyYes: () => ({
    data: { board_drafts: mocks.boardDrafts, seat_ratifications: [] },
    isLoading: false,
    isError: false,
    error: null,
  }),
  useSeatRoster: () => ({
    data: [],
    isLoading: false,
    isError: false,
    error: null,
  }),
  useRatifySeat: () => ({ mutate: rs.fn(), isPending: false, error: null }),
  useReopenSeat: () => ({ mutate: rs.fn(), isPending: false, error: null }),
}));

rs.mock("@/core/board", () => ({
  useApproveBoardReply: () => ({
    mutate: mocks.approveMutate,
    isPending: false,
    error: null,
  }),
  useSendBoardReply: () => ({
    mutate: mocks.sendMutate,
    isPending: false,
    error: null,
  }),
}));

function draft(
  overrides: Partial<BoardDraftAwaitingApproval>,
): BoardDraftAwaitingApproval {
  return {
    thread_id: "t1",
    client_id: null,
    kind: "ticket",
    subject: "Broken widget",
    status: "drafted",
    draft_body: "Here's a proposed reply.",
    updated_at: "2026-09-30T00:00:00.000Z",
    ...overrides,
  };
}

function renderWithClient() {
  const queryClient = new QueryClient();
  const invalidateQueries = rs.spyOn(queryClient, "invalidateQueries");
  render(
    <QueryClientProvider client={queryClient}>
      <CeoDeskBody />
    </QueryClientProvider>,
  );
  return { invalidateQueries };
}

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

describe("CEO Desk needs-my-yes queue, composing a reply inline (e14 next step)", () => {
  it("shows Momo's draft body and an Approve action for a drafted thread", () => {
    mocks.boardDrafts = [draft({ status: "drafted" })];
    const { invalidateQueries } = renderWithClient();

    expect(
      screen.getByLabelText<HTMLTextAreaElement>(
        "Momo's draft reply to Broken widget",
      ).value,
    ).toBe("Here's a proposed reply.");
    fireEvent.click(
      screen.getByRole("button", { name: "Approve Broken widget" }),
    );
    expect(mocks.sendMutate).not.toHaveBeenCalled();

    // f186(d): assert the real behavior of the second (options) argument,
    // not just that one was passed -- a no-op onSuccess would otherwise
    // satisfy the old `expect.anything()` assertion.
    const [args, options] = mocks.approveMutate.mock.calls[0]!;
    expect(args).toEqual({ threadId: "t1" });
    options.onSuccess();
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: CEO_NEEDS_MY_YES_QUERY_KEY,
    });
  });

  it("shows a Send reply action for an approved thread, using the draft body verbatim", () => {
    mocks.boardDrafts = [draft({ status: "approved" })];
    const { invalidateQueries } = renderWithClient();

    expect(
      screen.queryByRole("button", { name: "Approve Broken widget" }),
    ).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Send reply to Broken widget" }),
    );

    const [args, options] = mocks.sendMutate.mock.calls[0]!;
    expect(args).toEqual({
      threadId: "t1",
      body: "Here's a proposed reply.",
    });
    options.onSuccess();
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: CEO_NEEDS_MY_YES_QUERY_KEY,
    });
  });

  it("disables Send when there is no draft body to send", () => {
    mocks.boardDrafts = [draft({ status: "approved", draft_body: null })];
    renderWithClient();

    const sendButton = screen.getByRole<HTMLButtonElement>("button", {
      name: "Send reply to Broken widget",
    });
    expect(sendButton.disabled).toBe(true);
  });
});
