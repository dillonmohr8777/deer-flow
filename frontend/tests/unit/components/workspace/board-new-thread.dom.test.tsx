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

rs.mock("@/core/board", () => ({
  useBoardThreads: () => ({ data: [], isLoading: false, isError: false }),
  useBoardThread: () => ({ data: undefined, isLoading: true, isError: false }),
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
const allClientsData = [
  { id: "acme", display_name: "Acme Landscaping" },
  { id: "other-co", display_name: "Other Company" },
];

rs.mock("@/core/clients", () => ({
  useClients: () => ({ data: allClientsData }),
  useMyClients: () => ({ data: myClientsData, isLoading: false }),
}));

describe("Board new-thread form (e3: a client member can start a thread)", () => {
  afterEach(() => {
    cleanup();
    mockCreateMutate.mockClear();
    myClientsData = [{ id: "acme", display_name: "Acme Landscaping" }];
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
});
