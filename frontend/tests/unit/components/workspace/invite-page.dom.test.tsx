import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { StrictMode } from "react";

import InvitePage from "@/app/invite/page";

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("workspace invitations", () => {
  it("keeps a fragment invite through StrictMode, hides its URL token and never auto-accepts", async () => {
    window.history.replaceState(null, "", "/invite#token=private-invite");
    const fetcher = rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          email: "person@example.com",
          workspace_name: "Team",
          expires_at: "2026-10-01T00:00:00Z",
          requires_login: false,
        }),
      ),
    );
    render(
      <StrictMode>
        <InvitePage />
      </StrictMode>,
    );
    await screen.findByLabelText("New password");
    expect(window.location.hash).toBe("");
    expect(
      fetcher.mock.calls.every(
        ([path]) => path === "/api/v1/auth/invitations/inspect",
      ),
    ).toBe(true);
    expect(screen.queryByText(/Missing invite token/)).toBeNull();
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "one-strong-password" },
    });
    fireEvent.change(screen.getByLabelText("Confirm password"), {
      target: { value: "different-password" },
    });
    fireEvent.submit(
      screen.getByRole("button", { name: "Accept invite" }).closest("form")!,
    );
    await screen.findByText("Passwords do not match.");
    expect(
      fetcher.mock.calls.some(
        ([path]) => path === "/api/v1/auth/invitations/accept",
      ),
    ).toBe(false);
  });

  it("gives a missing-token visitor a way out instead of a dead end", async () => {
    const fetcher = rs.spyOn(globalThis, "fetch");
    render(<InvitePage />);
    await screen.findByText(/Missing invite token/);
    expect(
      screen
        .getByRole("link", { name: "Sign in instead" })
        .getAttribute("href"),
    ).toBe("/login");
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("accepts an existing account password without imposing the new-account length rule", async () => {
    window.history.replaceState(null, "", "/invite#token=existing-invite");
    const fetcher = rs
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            email: "person@example.com",
            workspace_name: "Team",
            expires_at: "2026-10-01T00:00:00Z",
            requires_login: true,
          }),
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Expired invitation" }), {
          status: 403,
        }),
      );
    render(<InvitePage />);
    const password = await screen.findByLabelText("Current password");
    fireEvent.change(password, { target: { value: "valid123" } });
    fireEvent.submit(
      screen.getByRole("button", { name: "Accept invite" }).closest("form")!,
    );
    await waitFor(() => expect(fetcher.mock.calls.length).toBe(2));
    expect(JSON.parse(fetcher.mock.calls[1]?.[1]?.body as string)).toEqual({
      token: "existing-invite",
      password: "valid123",
    });
    await screen.findByText("Expired invitation");
  });
});
