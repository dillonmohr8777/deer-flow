import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { BoardBody } from "@/components/workspace/board/board";

const mockCreateMutate = rs.fn(
  (
    input: { clientId: string; kind: string; subject: string },
    opts?: { onSuccess?: (thread: { id: string }) => void },
  ) => {
    opts?.onSuccess?.({ id: "new-thread-1" });
  },
);

// The just-created thread, as ThreadDetail would fetch it by id once
// selected. Kept separate from `boardThreadsData` below: the list query and
// the single-thread query are two different hooks with two different
// refresh timings, and that gap is exactly what the `!threads.isFetching`
// guard in BoardBody exists to survive.
const NEW_THREAD = {
  id: "new-thread-1",
  client_id: "acme",
  kind: "concern",
  status: "new",
  subject: "Invoice question",
  created_by_user_id: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

// `useBoardThreads`' list query. Mutable so a test can simulate the create
// mutation's `invalidateQueries` still being in flight (data not yet
// refreshed, isFetching true) at the exact moment `selectedId` is set to a
// thread the list doesn't contain yet.
let boardThreadsData: unknown[] = [];
let boardThreadsFetching = false;

rs.mock("@/core/board", () => ({
  useBoardThreads: () => ({
    data: boardThreadsData,
    isLoading: false,
    isError: false,
    isFetching: boardThreadsFetching,
  }),
  useBoardThread: (threadId: string | null) =>
    threadId === NEW_THREAD.id
      ? { data: NEW_THREAD, isLoading: false, isError: false }
      : { data: undefined, isLoading: true, isError: false },
  useBoardMessages: () => ({ data: [], isLoading: false, isError: false }),
  useDraftBoardReply: () => ({
    mutate: rs.fn(),
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
  useCreateBoardThread: () => ({
    mutate: mockCreateMutate,
    isPending: false,
    isError: false,
    error: null,
  }),
}));

// The org's full client roster (what an owner sees via /api/clients) is
// deliberately larger than "my clients" -- the create-thread picker must
// only ever offer the second, scoped list. Mutable so individual tests can
// swap in an empty assignment set without re-hoisting the module mock.
let myClientsData: { id: string; display_name: string }[] = [
  { id: "acme", display_name: "Acme Landscaping" },
];
let myClientsIsError = false;
const myClientsRefetch = rs.fn();
const allClientsData = [
  { id: "acme", display_name: "Acme Landscaping" },
  { id: "other-co", display_name: "Other Company" },
];

rs.mock("@/core/clients", () => ({
  useClients: () => ({ data: allClientsData }),
  useMyClients: () => ({
    data: myClientsData,
    isLoading: false,
    isError: myClientsIsError,
    error: myClientsIsError ? new Error("network down") : null,
    refetch: myClientsRefetch,
  }),
}));

describe("Board new-thread form (e3: a client member can start a thread)", () => {
  afterEach(() => {
    cleanup();
    mockCreateMutate.mockClear();
    myClientsRefetch.mockClear();
    myClientsData = [{ id: "acme", display_name: "Acme Landscaping" }];
    myClientsIsError = false;
    boardThreadsData = [];
    boardThreadsFetching = false;
  });

  it("scopes the client picker to the caller's own clients, not the full roster", () => {
    render(<BoardBody />);
    fireEvent.click(screen.getByRole("button", { name: "New thread" }));

    const clientSelect = screen.getByLabelText<HTMLSelectElement>("Client");
    const optionLabels = Array.from(clientSelect.options).map(
      (o) => o.textContent,
    );
    expect(optionLabels).toEqual(["Acme Landscaping"]);
    expect(optionLabels).not.toContain("Other Company");
  });

  it("starts a thread for the selected client and kind, then selects it", () => {
    // The exact race f42 flagged: the create mutation's invalidateQueries
    // has kicked off a refetch (isFetching true) but the list still hasn't
    // caught up to include the new thread. Without BoardBody's
    // `!threads.isFetching` guard on its "clear a no-longer-listed
    // selection" effect, selectedId would be reset to null right after
    // being set, and ThreadDetail would never render.
    boardThreadsData = [];
    boardThreadsFetching = true;

    render(<BoardBody />);
    fireEvent.click(screen.getByRole("button", { name: "New thread" }));

    fireEvent.change(screen.getByLabelText("Kind"), {
      target: { value: "concern" },
    });
    fireEvent.change(screen.getByLabelText("Subject"), {
      target: { value: "Invoice question" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start thread" }));

    expect(mockCreateMutate).toHaveBeenCalledWith(
      { clientId: "acme", kind: "concern", subject: "Invoice question" },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
    // A successful create closes the form (onCreated -> setShowCreate(false)).
    expect(screen.queryByRole("button", { name: "Start thread" })).toBeNull();
    expect(screen.getByRole("button", { name: "New thread" })).toBeDefined();
    // And it's actually selected: ThreadDetail renders the new thread, not
    // the "Pick a thread" empty state.
    expect(screen.getByTestId("board-thread")).toBeDefined();
    expect(screen.getByText("Invoice question")).toBeDefined();
    expect(screen.queryByText("Pick a thread")).toBeNull();
  });

  it("tells a client with no assignment there's nowhere to start a thread", () => {
    myClientsData = [];
    render(<BoardBody />);
    fireEvent.click(screen.getByRole("button", { name: "New thread" }));

    expect(
      screen.getByText(
        "You aren't assigned to any client yet, so there's nowhere to start a thread.",
      ),
    ).toBeDefined();
    expect(screen.queryByRole("button", { name: "Start thread" })).toBeNull();
  });

  it("shows an error with retry when the caller's clients fail to load", () => {
    myClientsIsError = true;
    render(<BoardBody />);
    fireEvent.click(screen.getByRole("button", { name: "New thread" }));

    // f42: a failed read must never render as "you have no clients".
    expect(
      screen.queryByText(
        "You aren't assigned to any client yet, so there's nowhere to start a thread.",
      ),
    ).toBeNull();
    expect(screen.getByText("Couldn't load your clients.")).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(myClientsRefetch).toHaveBeenCalled();
  });
});
