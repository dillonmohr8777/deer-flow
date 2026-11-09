import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ApprovalsBody } from "@/components/workspace/approvals/approvals";
import {
  fieldsFor,
  isReadyToSend,
  socialPostLink,
  statusText,
  statusTone,
} from "@/components/workspace/approvals/approvals-data";
import type { Approval } from "@/core/approvals";

const mocks = rs.hoisted(() => ({
  rows: [] as Approval[],
  statusArg: undefined as string | undefined,
  edit: rs.fn(),
  approve: rs.fn(),
  reject: rs.fn(),
}));

const idle = { isPending: false, isError: false, error: null };

rs.mock("@/core/approvals", () => ({
  useApprovals: (status?: string) => {
    mocks.statusArg = status;
    return {
      data: mocks.rows,
      isLoading: false,
      isError: false,
      error: null,
      refetch: rs.fn(),
    };
  },
  useEditApproval: () => ({ ...idle, mutate: mocks.edit }),
  useApproveApproval: () => ({ ...idle, mutate: mocks.approve }),
  useRejectApproval: () => ({ ...idle, mutate: mocks.reject }),
}));

function approval(patch: Partial<Approval> = {}): Approval {
  return {
    id: "a1",
    action_type: "slack_message",
    title: "Tell the team",
    target: "C123",
    payload: { text: "hello" },
    original_payload: { text: "hello" },
    status: "pending",
    thread_id: "thread-9",
    run_id: "run-12345678",
    agent_name: "momo",
    decided_by: null,
    decided_at: null,
    executed_at: null,
    execution_result: null,
    error: null,
    created_at: "2026-10-05T10:00:00Z",
    updated_at: "2026-10-05T10:00:00Z",
    ...patch,
  };
}

describe("ApprovalsBody", () => {
  beforeEach(() => {
    mocks.rows = [approval()];
    mocks.edit.mockClear();
    mocks.approve.mockClear();
    mocks.reject.mockClear();
  });
  afterEach(() => {
    cleanup();
    rs.restoreAllMocks();
  });

  it("opens mobile detail and restores the proposal on Back", () => {
    const media = window.matchMedia("(max-width: 63.999rem)");
    rs.spyOn(window, "matchMedia").mockReturnValue({ ...media, matches: true });
    render(<ApprovalsBody />);
    const row = screen.getByRole("button", { name: /Tell the team/ });
    fireEvent.click(row);
    expect(document.activeElement).toBe(
      screen.getByRole("region", { name: "Approval detail" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Back to proposed actions" }),
    );
    expect(document.activeElement).toBe(row);
    expect(
      row.closest("[data-mobile-view]")?.getAttribute("data-mobile-view"),
    ).toBe("list");
  });

  it("keeps editor focus when the selected approval refreshes", () => {
    const media = window.matchMedia("(max-width: 63.999rem)");
    rs.spyOn(window, "matchMedia").mockReturnValue({ ...media, matches: true });
    const { rerender } = render(<ApprovalsBody />);
    fireEvent.click(screen.getByRole("button", { name: /Tell the team/ }));
    const message = screen.getByLabelText("Message");
    message.focus();
    mocks.rows = [approval({ updated_at: "2026-10-05T11:00:00Z" })];
    rerender(<ApprovalsBody />);
    expect(document.activeElement).toBe(message);
  });

  it("defaults to the pending filter and lists proposals", () => {
    render(<ApprovalsBody />);
    expect(mocks.statusArg).toBe("pending");
    expect(screen.getByText("Tell the team")).toBeTruthy();
  });

  it("filters by status", () => {
    render(<ApprovalsBody />);
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(mocks.statusArg).toBeUndefined();
    fireEvent.click(screen.getByRole("button", { name: "Failed" }));
    expect(mocks.statusArg).toBe("failed");
  });

  it("shows an empty state", () => {
    mocks.rows = [];
    render(<ApprovalsBody />);
    expect(screen.getByText(/Nothing is waiting on you/)).toBeTruthy();
  });

  it("links to the source conversation", () => {
    render(<ApprovalsBody />);
    fireEvent.click(screen.getByText("Tell the team"));
    const link = screen.getByRole("link", {
      name: /conversation that proposed/,
    });
    expect(link.getAttribute("href")).toBe("/workspace/chats/thread-9");
  });

  it("approves only an unedited item and never before a click", () => {
    render(<ApprovalsBody />);
    expect(mocks.approve).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Tell the team"));
    fireEvent.click(screen.getByRole("button", { name: "Approve and send" }));
    expect(mocks.approve).toHaveBeenCalledWith({ id: "a1" });
  });

  it("requires saving edits before approving, and saves the edited payload", () => {
    render(<ApprovalsBody />);
    fireEvent.click(screen.getByText("Tell the team"));
    fireEvent.change(screen.getByLabelText("Message"), {
      target: { value: "better words" },
    });
    const approveButton = screen.getByRole<HTMLButtonElement>("button", {
      name: "Approve and send",
    });
    expect(approveButton.disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Save edits" }));
    expect(mocks.edit).toHaveBeenCalledWith({
      id: "a1",
      edit: { target: "C123", payload: { text: "better words" } },
    });
  });

  it("shows fact-check flags next to claims, with the source when supported", () => {
    mocks.rows = [
      approval({
        fact_check: {
          gate: "flag",
          counts: { supported: 1, unsupported: 1 },
          claims: [
            {
              id: 1,
              text: "The new ad hit a 55% CTR.",
              raw: "55%",
              kind: "pct",
              verdict: "unsupported",
              reason: "no evidence in this run",
              evidence: null,
              conflicting: null,
            },
            {
              id: 2,
              text: "Google Ads showed 537 queries.",
              raw: "537",
              kind: "plain",
              verdict: "supported",
              reason: "",
              evidence: "google_ads_search_terms",
              conflicting: null,
            },
          ],
        },
      }),
    ];
    render(<ApprovalsBody />);
    fireEvent.click(screen.getByText("Tell the team"));
    expect(screen.getByText("Unsourced")).toBeTruthy();
    expect(screen.getByText(/The new ad hit a 55% CTR/)).toBeTruthy();
    expect(screen.getByText("Sourced")).toBeTruthy();
    expect(screen.getByText(/Source: google_ads_search_terms/)).toBeTruthy();
  });

  it("shows no fact-check section without claims", () => {
    render(<ApprovalsBody />);
    fireEvent.click(screen.getByText("Tell the team"));
    expect(screen.queryByLabelText("Fact check")).toBeNull();
  });

  it("rejects", () => {
    render(<ApprovalsBody />);
    fireEvent.click(screen.getByText("Tell the team"));
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(mocks.reject).toHaveBeenCalledWith({ id: "a1" });
  });

  it("edits ad changes as JSON and blocks invalid JSON", () => {
    mocks.rows = [
      approval({ action_type: "ad_change", payload: { change: "pause" } }),
    ];
    render(<ApprovalsBody />);
    fireEvent.click(screen.getByText("Tell the team"));
    fireEvent.change(screen.getByLabelText("Details (JSON)"), {
      target: { value: "{nope" },
    });
    expect(screen.getByText("Payload is not valid JSON.")).toBeTruthy();
    expect(
      screen.getByRole<HTMLButtonElement>("button", { name: "Save edits" })
        .disabled,
    ).toBe(true);
  });

  it("is read-only after a decision and explains a stubbed send", () => {
    mocks.rows = [
      approval({
        action_type: "email",
        target: "c@example.com",
        payload: { subject: "Hi", body: "Report" },
        status: "approved",
        decided_at: "2026-10-05T11:00:00Z",
        execution_result: {
          state: "ready_to_send",
          note: "Send this manually.",
        },
      }),
    ];
    render(<ApprovalsBody />);
    fireEvent.click(screen.getByText("Tell the team"));
    expect(
      screen.queryByRole("button", { name: "Approve and send" }),
    ).toBeNull();
    expect(screen.getByText("Send this manually.")).toBeTruthy();
    expect(screen.getByLabelText<HTMLInputElement>("Subject").disabled).toBe(
      true,
    );
  });

  it("shows a social post's exact text, where it appears, and approve-to-publish", () => {
    mocks.rows = [
      approval({
        action_type: "social_post",
        title: "Social post: Fresh sourdough",
        target: "momobot_page",
        payload: { text: "Fresh sourdough is out of the oven." },
        destination_url:
          "/api/public/social/maple-street-bakery-1a2b3c4d5e6f7a8b",
      }),
    ];
    render(<ApprovalsBody />);
    fireEvent.click(screen.getByText("Social post: Fresh sourdough"));
    expect(screen.getByLabelText<HTMLTextAreaElement>("Post").value).toBe(
      "Fresh sourdough is out of the oven.",
    );
    expect(screen.getByText(/Your MomoBot page only/)).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Open your MomoBot page" })
        .getAttribute("href"),
    ).toBe("/api/public/social/maple-street-bakery-1a2b3c4d5e6f7a8b");
    fireEvent.click(
      screen.getByRole("button", { name: "Approve and publish" }),
    );
    expect(mocks.approve).toHaveBeenCalledWith({ id: "a1" });
  });

  it("never renders a social post link planted in the payload", () => {
    mocks.rows = [
      approval({
        action_type: "social_post",
        title: "Social post: Planted",
        target: "momobot_page",
        payload: { text: "Hello.", page_url: "https://evil.example/p" },
      }),
    ];
    render(<ApprovalsBody />);
    fireEvent.click(screen.getByText("Social post: Planted"));
    expect(screen.getByText(/Your MomoBot page only/)).toBeTruthy();
    expect(
      screen.queryByRole("link", { name: "Open your MomoBot page" }),
    ).toBeNull();
  });

  it("links a published social post to its live page", () => {
    mocks.rows = [
      approval({
        action_type: "social_post",
        title: "Social post: Rye",
        target: "momobot_page",
        payload: { text: "Rye loaves today." },
        status: "executed",
        decided_at: "2026-10-05T11:00:00Z",
        execution_result: { delivery: "momobot_page" },
        destination_url:
          "/api/public/social/maple-street-bakery-1a2b3c4d5e6f7a8b",
      }),
    ];
    render(<ApprovalsBody />);
    fireEvent.click(screen.getByText("Social post: Rye"));
    expect(
      screen
        .getByRole("link", { name: "See it live on your MomoBot page" })
        .getAttribute("href"),
    ).toBe("/api/public/social/maple-street-bakery-1a2b3c4d5e6f7a8b");
    expect(screen.getAllByText("Published").length).toBeGreaterThan(0);
  });
});

describe("approvals-data", () => {
  it("maps tone and detects stubbed sends", () => {
    expect(statusTone("pending")).toBe("attention");
    expect(statusTone("failed")).toBe("danger");
    expect(
      isReadyToSend(
        approval({
          status: "approved",
          execution_result: { state: "ready_to_send" },
        }),
      ),
    ).toBe(true);
    expect(isReadyToSend(approval({ status: "executed" }))).toBe(false);
    expect(fieldsFor("ad_change")).toBeNull();
    expect(fieldsFor("email")?.map((f) => f.key)).toEqual(["subject", "body"]);
    expect(fieldsFor("social_post")?.map((f) => f.key)).toEqual([
      "text",
      "link",
    ]);
  });

  it("only renders safe social post links and labels failures", () => {
    const post = (patch: Partial<Approval>) =>
      approval({
        action_type: "social_post",
        target: "momobot_page",
        ...patch,
      });
    expect(
      socialPostLink(post({ destination_url: "javascript:1" })),
    ).toBeNull();
    expect(
      socialPostLink(post({ destination_url: "//evil.test/p" })),
    ).toBeNull();
    // A link planted in the payload or execution result is never rendered.
    expect(
      socialPostLink(
        post({
          payload: { text: "x", page_url: "https://evil.example/p" },
          execution_result: { live_url: "https://evil.example/p" },
        }),
      ),
    ).toBeNull();
    expect(
      socialPostLink(
        post({
          payload: { text: "x", page_url: "https://evil.example/p" },
          destination_url:
            "/api/public/social/maple-street-bakery-1a2b3c4d5e6f7a8b",
        }),
      ),
    ).toBe("/api/public/social/maple-street-bakery-1a2b3c4d5e6f7a8b");
    expect(socialPostLink(approval())).toBeNull();
    expect(statusText(post({ status: "failed" }))).toBe("Failed");
    expect(statusText(post({ status: "executed" }))).toBe("Published");
  });
});
