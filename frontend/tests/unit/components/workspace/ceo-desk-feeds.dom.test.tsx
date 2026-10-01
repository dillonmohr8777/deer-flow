import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";

import { CeoDeskBody } from "@/components/workspace/ceo-desk/ceo-desk";
import type { CeoFeed, CeoFeedSlug } from "@/core/ceo-desk";

const mocks = rs.hoisted(() => ({
  feeds: {} as Record<CeoFeedSlug, CeoFeed>,
  postMutate: rs.fn(),
  momentumInternalEnabled: rs.fn(() => ({ enabled: true, isLoading: false })),
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
    data: { board_drafts: [], seat_ratifications: [] },
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
  useCeoFeed: (slug: CeoFeedSlug) => ({
    data: mocks.feeds[slug],
    isLoading: false,
    isError: false,
    error: null,
  }),
  usePostCeoFeedMessage: () => ({
    mutate: mocks.postMutate,
    isPending: false,
    error: null,
  }),
}));

rs.mock("@/core/board", () => ({
  useApproveBoardReply: () => ({
    mutate: rs.fn(),
    isPending: false,
    error: null,
  }),
  useSendBoardReply: () => ({ mutate: rs.fn(), isPending: false, error: null }),
}));

rs.mock("@/core/team", () => ({
  useTeamMembers: () => ({
    data: [
      {
        user_id: "user-a",
        email: "dillon.mohr@momentum.example",
        role: "owner",
      },
    ],
    isLoading: false,
    isError: false,
    error: null,
  }),
}));

rs.mock("@/core/features", () => ({
  useCeoDeskEnabled: () => ({ enabled: true, isLoading: false }),
  // The feeds are Momentum-staff only (f189); these tests exercise a staff
  // caller, matching the agency workspace the real /api/ceo feed routes gate on.
  useMomentumInternalEnabled: mocks.momentumInternalEnabled,
}));

rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "user-a" } }),
}));

function renderBody() {
  const queryClient = new QueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <CeoDeskBody />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

describe("CEO Desk live #exec/#fleet feeds (e14 live feeds)", () => {
  it("reads #exec messages, labels the signed-in owner as You, and composes a reply", () => {
    mocks.feeds = {
      exec: {
        channel: "exec",
        exists: true,
        messages: [
          {
            id: "m1",
            author_user_id: "user-a",
            body: "ratified cmo for cmo-agent via CEO Desk",
            created_at: "2026-09-30T12:00:00.000Z",
          },
        ],
      },
      fleet: { channel: "fleet", exists: false, messages: [] },
    };
    renderBody();

    const execPanel = screen.getByTestId("ceo-feed-exec");
    expect(within(execPanel).getByText("You")).toBeTruthy();
    expect(
      within(execPanel).getByText(/ratified cmo for cmo-agent/),
    ).toBeTruthy();

    const composer = within(execPanel).getByLabelText("Message #exec");
    fireEvent.change(composer, { target: { value: "Shipping today." } });
    fireEvent.click(within(execPanel).getByRole("button", { name: "Send" }));

    expect(mocks.postMutate).toHaveBeenCalledWith(
      "Shipping today.",
      expect.anything(),
    );
  });

  it("shows a not-yet-created state for #fleet with no composer, until it exists", () => {
    mocks.feeds = {
      exec: { channel: "exec", exists: true, messages: [] },
      fleet: { channel: "fleet", exists: false, messages: [] },
    };
    renderBody();

    const fleetPanel = screen.getByTestId("ceo-feed-fleet");
    expect(within(fleetPanel).getByText(/No #fleet channel yet/)).toBeTruthy();
    expect(within(fleetPanel).queryByLabelText("Message #fleet")).toBeNull();
  });

  it("hides the feeds entirely off the agency workspace (f189)", () => {
    mocks.feeds = {
      exec: { channel: "exec", exists: true, messages: [] },
      fleet: { channel: "fleet", exists: false, messages: [] },
    };
    mocks.momentumInternalEnabled.mockReturnValueOnce({
      enabled: false,
      isLoading: false,
    });
    renderBody();

    expect(screen.queryByText("Live feeds")).toBeNull();
    expect(screen.queryByTestId("ceo-feed-exec")).toBeNull();
  });

  it("scrolls only the feed list on a new message, never the page (f190)", () => {
    mocks.feeds = {
      exec: {
        channel: "exec",
        exists: true,
        messages: [
          {
            id: "m1",
            author_user_id: "user-a",
            body: "first",
            created_at: "2026-09-30T12:00:00.000Z",
          },
        ],
      },
      fleet: { channel: "fleet", exists: false, messages: [] },
    };
    const scrollIntoView = rs.fn();
    // happy-dom has no real layout, so scrollHeight is always 0; the
    // assertion that matters is that scrollIntoView (which walks every
    // scrollable ancestor, including the page) is never called.
    HTMLElement.prototype.scrollIntoView = scrollIntoView;
    renderBody();

    expect(scrollIntoView).not.toHaveBeenCalled();
  });

  it("names a fleet-agent's signed message as Momentum, not Former teammate", () => {
    mocks.feeds = {
      exec: {
        channel: "exec",
        exists: true,
        messages: [
          {
            id: "m2",
            author_user_id: "fleet-service-account",
            body: "[cmo-agent] pipeline review posted",
            created_at: "2026-09-30T12:00:00.000Z",
          },
        ],
      },
      fleet: { channel: "fleet", exists: false, messages: [] },
    };
    renderBody();

    const execPanel = screen.getByTestId("ceo-feed-exec");
    expect(within(execPanel).getByText("Momentum")).toBeTruthy();
  });
});
