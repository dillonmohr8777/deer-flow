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
  window.sessionStorage.clear();
  window.history.replaceState(null, "", "/");
});

const INSPECT = "/api/v1/auth/invitations/inspect";
const ACCEPT = "/api/v1/auth/invitations/accept";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

/** A fetch stub that answers by path, so call order doesn't matter. */
function routeFetch(routes: Record<string, () => Response>) {
  return rs
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input: RequestInfo | URL) => {
      const path =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url;
      const handler = routes[path];
      return handler ? handler() : json({ detail: "unexpected" }, 404);
    });
}

const ssoInvite = {
  email: "jesse@example.com",
  workspace_name: "Momentum",
  expires_at: "2026-10-01T00:00:00Z",
  requires_login: true,
  sign_in: "sso",
};
const google = {
  providers: [{ id: "google", display_name: "Google", type: "oidc" }],
};

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
    // The token only ever travels to the inspect call (the SSO provider
    // lookup a new invitee triggers carries no token).
    const carryingToken = fetcher.mock.calls.filter(
      ([, init]) =>
        typeof init?.body === "string" && init.body.includes("private-invite"),
    );
    expect(carryingToken.length).toBeGreaterThan(0);
    expect(
      carryingToken.every(
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
    await screen.findByText("Passwords don't match.");
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

  it("lets a signed-in Google account accept with no password field", async () => {
    window.history.replaceState(null, "", "/invite#token=sso-invite");
    const fetcher = routeFetch({
      [INSPECT]: () => json(ssoInvite),
      "/api/v1/auth/providers": () => json(google),
      "/api/v1/auth/me": () => json({ id: "u1", email: "Jesse@Example.com" }),
      [ACCEPT]: () => json({ detail: "Expired invitation" }, 403),
    });
    render(<InvitePage />);
    await screen.findByText(
      "You're signed in as jesse@example.com. Accept to join.",
    );
    expect(screen.queryByLabelText(/password/i)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Accept invite" }));
    await screen.findByText("Expired invitation");
    const acceptCall = fetcher.mock.calls.find(([path]) => path === ACCEPT);
    expect(JSON.parse(acceptCall?.[1]?.body as string)).toEqual({
      token: "sso-invite",
    });
  });

  it("sends a signed-out Google invitee to Google and keeps the token out of the URL", async () => {
    window.history.replaceState(null, "", "/invite#token=sso-invite");
    const fetcher = routeFetch({
      [INSPECT]: () => json(ssoInvite),
      "/api/v1/auth/providers": () => json(google),
      "/api/v1/auth/me": () => json({ detail: "Not signed in" }, 401),
    });
    render(<InvitePage />);
    await screen.findByText("Sign in as jesse@example.com to accept.");
    expect(screen.queryByRole("button", { name: "Accept invite" })).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Continue with Google" }),
    );
    expect(window.sessionStorage.getItem("momobot.invite.token")).toBe(
      "sso-invite",
    );
    expect(fetcher.mock.calls.some(([path]) => path === ACCEPT)).toBe(false);
  });

  it("warns when the session belongs to someone else", async () => {
    window.history.replaceState(null, "", "/invite#token=sso-invite");
    routeFetch({
      [INSPECT]: () => json(ssoInvite),
      "/api/v1/auth/providers": () => json(google),
      "/api/v1/auth/me": () => json({ id: "u2", email: "other@example.com" }),
    });
    render(<InvitePage />);
    await screen.findByText(
      "You're signed in as other@example.com, but this invite is for jesse@example.com. Sign in as jesse@example.com to accept.",
    );
    expect(screen.queryByRole("button", { name: "Accept invite" })).toBeNull();
  });

  it("resumes from the stashed token after the Google round trip", async () => {
    window.history.replaceState(null, "", "/invite");
    window.sessionStorage.setItem("momobot.invite.token", "stashed-invite");
    const fetcher = routeFetch({
      [INSPECT]: () => json(ssoInvite),
      "/api/v1/auth/providers": () => json(google),
      "/api/v1/auth/me": () => json({ id: "u1", email: "jesse@example.com" }),
    });
    render(<InvitePage />);
    await screen.findByRole("button", { name: "Accept invite" });
    const inspectCall = fetcher.mock.calls.find(([path]) => path === INSPECT);
    expect(JSON.parse(inspectCall?.[1]?.body as string)).toEqual({
      token: "stashed-invite",
    });
    expect(screen.queryByText(/Missing invite token/)).toBeNull();
  });

  it("offers Google as well as a password to a brand-new invitee", async () => {
    window.history.replaceState(null, "", "/invite#token=new-invite");
    routeFetch({
      [INSPECT]: () =>
        json({ ...ssoInvite, requires_login: false, sign_in: "new" }),
      "/api/v1/auth/providers": () => json(google),
    });
    render(<InvitePage />);
    await screen.findByLabelText("New password");
    await screen.findByRole("button", { name: "Continue with Google" });
    screen.getByText("Or skip the password: sign in with jesse@example.com.");
  });

  it("forgets a stashed token the server rejects", async () => {
    window.history.replaceState(null, "", "/invite");
    window.sessionStorage.setItem("momobot.invite.token", "dead-invite");
    routeFetch({
      [INSPECT]: () =>
        json({ detail: "Invitation is invalid or no longer available" }, 403),
    });
    render(<InvitePage />);
    await screen.findByText("Invitation is invalid or no longer available");
    expect(window.sessionStorage.getItem("momobot.invite.token")).toBeNull();
  });
});
