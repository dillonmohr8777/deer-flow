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

const STASH_KEY = "momobot.invite.token";
const TEN_MINUTES_MS = 10 * 60 * 1000;

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
  window.sessionStorage.clear();
  window.history.replaceState(null, "", "/");
  document.cookie =
    "csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
});

const INSPECT = "/api/v1/auth/invitations/inspect";
const ACCEPT = "/api/v1/auth/invitations/accept";
const PROVIDERS = "/api/v1/auth/providers";
const ME = "/api/v1/auth/me";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

function pathOf(input: RequestInfo | URL): string {
  return typeof input === "string"
    ? input
    : input instanceof URL
      ? input.href
      : input.url;
}

/** A fetch stub that answers by path, so call order doesn't matter. */
function routeFetch(routes: Record<string, () => Response>) {
  return rs
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input: RequestInfo | URL) => {
      const handler = routes[pathOf(input)];
      return handler ? handler() : json({ detail: "unexpected" }, 404);
    });
}

type FetchSpy = ReturnType<typeof routeFetch>;

/** Every call that carried the token anywhere: URL or body. */
function callsCarrying(fetcher: FetchSpy, token: string) {
  return fetcher.mock.calls.filter(
    ([input, init]) =>
      pathOf(input).includes(token) ||
      (typeof init?.body === "string" && init.body.includes(token)),
  );
}

function stash(token: string, savedAt = Date.now()) {
  window.sessionStorage.setItem(STASH_KEY, JSON.stringify({ token, savedAt }));
}

function readStash(): { token?: unknown; savedAt?: unknown } | null {
  const raw = window.sessionStorage.getItem(STASH_KEY);
  return raw
    ? (JSON.parse(raw) as { token?: unknown; savedAt?: unknown })
    : null;
}

/** Stop happy-dom following a clicked link once React has handled it. */
function stayOnPage(): () => void {
  const block = (event: Event) => event.preventDefault();
  document.addEventListener("click", block);
  return () => document.removeEventListener("click", block);
}

const existingInvite = {
  email: "jesse@example.com",
  workspace_name: "Momentum",
  expires_at: "2026-10-01T00:00:00Z",
  requires_login: true,
};
const newInvite = { ...existingInvite, requires_login: false };
const google = {
  providers: [{ id: "google", display_name: "Google", type: "oidc" }],
};

describe("workspace invitations", () => {
  it("keeps a fragment invite through StrictMode, hides its URL token and never auto-accepts", async () => {
    window.history.replaceState(null, "", "/invite#token=private-invite");
    const fetcher = routeFetch({
      [INSPECT]: () =>
        json({
          email: "person@example.com",
          workspace_name: "Team",
          expires_at: "2026-10-01T00:00:00Z",
          requires_login: false,
        }),
      [PROVIDERS]: () => json({ providers: [] }),
    });
    render(
      <StrictMode>
        <InvitePage />
      </StrictMode>,
    );
    await screen.findByLabelText("New password");
    expect(window.location.hash).toBe("");
    // The token only ever travels in the inspect body (the SSO provider
    // lookup a new invitee triggers carries no token), and a fragment load
    // leaves nothing behind in storage.
    const carryingToken = callsCarrying(fetcher, "private-invite");
    expect(carryingToken.length).toBeGreaterThan(0);
    expect(carryingToken.every(([input]) => pathOf(input) === INSPECT)).toBe(
      true,
    );
    expect(window.sessionStorage.getItem(STASH_KEY)).toBeNull();
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
    expect(fetcher.mock.calls.some(([input]) => pathOf(input) === ACCEPT)).toBe(
      false,
    );
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

  it("asks a signed-out existing account to sign in first, with no password field", async () => {
    window.history.replaceState(null, "", "/invite#token=existing-invite");
    const fetcher = routeFetch({
      [INSPECT]: () => json(existingInvite),
      [PROVIDERS]: () => json(google),
      [ME]: () => json({ detail: "Not signed in" }, 401),
    });
    render(<InvitePage />);
    await screen.findByText("Sign in as jesse@example.com to accept.");
    expect(screen.queryByLabelText(/password/i)).toBeNull();
    expect(screen.queryByRole("button", { name: "Accept invite" })).toBeNull();
    screen.getByRole("button", { name: "Continue with Google" });
    const passwordSignIn = screen.getByRole("link", {
      name: "Sign in with password",
    });
    expect(passwordSignIn.getAttribute("href")).toBe("/login?next=%2Finvite");
    // Nothing waits in storage until the person actually leaves to sign in.
    expect(window.sessionStorage.getItem(STASH_KEY)).toBeNull();

    const release = stayOnPage();
    try {
      const before = Date.now();
      fireEvent.click(passwordSignIn);
      const stashed = readStash();
      expect(stashed?.token).toBe("existing-invite");
      expect(typeof stashed?.savedAt).toBe("number");
      expect(stashed!.savedAt as number).toBeGreaterThanOrEqual(before);
      expect(stashed!.savedAt as number).toBeLessThanOrEqual(Date.now());
    } finally {
      release();
    }
    expect(fetcher.mock.calls.some(([input]) => pathOf(input) === ACCEPT)).toBe(
      false,
    );
    expect(
      callsCarrying(fetcher, "existing-invite").every(
        ([input]) => pathOf(input) === INSPECT,
      ),
    ).toBe(true);
  });

  it("sends a signed-out invitee to Google with the token stashed, never in the URL", async () => {
    window.history.replaceState(null, "", "/invite#token=sso-invite");
    const fetcher = routeFetch({
      [INSPECT]: () => json(existingInvite),
      [PROVIDERS]: () => json(google),
      [ME]: () => json({ detail: "Not signed in" }, 401),
    });
    const assign = rs
      .spyOn(window.location, "assign")
      .mockImplementation(() => undefined);
    render(<InvitePage />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Continue with Google" }),
    );
    expect(assign).toHaveBeenCalledWith(
      "/api/v1/auth/oauth/google?next=%2Finvite&remember_me=true",
    );
    expect(readStash()?.token).toBe("sso-invite");
    expect(fetcher.mock.calls.some(([input]) => pathOf(input) === ACCEPT)).toBe(
      false,
    );
  });

  it("drops the round-trip stash when Back restores the page from the cache", async () => {
    window.history.replaceState(null, "", "/invite#token=sso-invite");
    routeFetch({
      [INSPECT]: () => json(existingInvite),
      [PROVIDERS]: () => json(google),
      [ME]: () => json({ detail: "Not signed in" }, 401),
    });
    rs.spyOn(window.location, "assign").mockImplementation(() => undefined);
    render(<InvitePage />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Continue with Google" }),
    );
    expect(readStash()?.token).toBe("sso-invite");
    const restored = new Event("pageshow");
    Object.defineProperty(restored, "persisted", { value: true });
    window.dispatchEvent(restored);
    expect(window.sessionStorage.getItem(STASH_KEY)).toBeNull();
    // The page still holds the token, so signing in again re-stashes it.
    fireEvent.click(
      screen.getByRole("button", { name: "Continue with Google" }),
    );
    expect(readStash()?.token).toBe("sso-invite");
  });

  it("lets the signed-in invitee accept with one button that posts only the token", async () => {
    window.history.replaceState(null, "", "/invite#token=existing-invite");
    document.cookie = "csrf_token=csrf-from-cookie; path=/";
    const fetcher = routeFetch({
      [INSPECT]: () => json(existingInvite),
      [PROVIDERS]: () => json(google),
      [ME]: () => json({ id: "u1", email: "Jesse@Example.com" }),
      [ACCEPT]: () => json({ detail: "Expired invitation" }, 403),
    });
    render(<InvitePage />);
    await screen.findByText(
      "You're signed in as jesse@example.com. Accept to join.",
    );
    expect(screen.queryByLabelText(/password/i)).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Continue with Google" }),
    ).toBeNull();
    expect(
      screen.queryByRole("link", { name: "Sign in with password" }),
    ).toBeNull();
    expect(screen.getAllByRole("button")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Accept invite" }));
    await screen.findByText("Expired invitation");
    const acceptCall = fetcher.mock.calls.find(
      ([input]) => pathOf(input) === ACCEPT,
    );
    expect(JSON.parse(acceptCall?.[1]?.body as string)).toEqual({
      token: "existing-invite",
    });
    // The Gateway requires the double-submit pair when a session accepts.
    expect(
      (acceptCall?.[1]?.headers as Record<string, string>)["X-CSRF-Token"],
    ).toBe("csrf-from-cookie");
  });

  it("warns when the session belongs to someone else and offers both ways to sign in", async () => {
    window.history.replaceState(null, "", "/invite#token=existing-invite");
    routeFetch({
      [INSPECT]: () => json(existingInvite),
      [PROVIDERS]: () => json(google),
      [ME]: () => json({ id: "u2", email: "other@example.com" }),
    });
    render(<InvitePage />);
    await screen.findByText(
      "You're signed in as other@example.com, but this invite is for jesse@example.com. Sign in as jesse@example.com to accept.",
    );
    expect(screen.queryByRole("button", { name: "Accept invite" })).toBeNull();
    screen.getByRole("button", { name: "Continue with Google" });
    screen.getByRole("link", { name: "Sign in with password" });
  });

  it("offers password sign-in even when no SSO provider is configured", async () => {
    window.history.replaceState(null, "", "/invite#token=existing-invite");
    routeFetch({
      [INSPECT]: () => json(existingInvite),
      [PROVIDERS]: () => json({ providers: [] }),
      [ME]: () => json({ detail: "Not signed in" }, 401),
    });
    render(<InvitePage />);
    await screen.findByRole("link", { name: "Sign in with password" });
    expect(screen.queryByRole("button", { name: /Continue with/ })).toBeNull();
  });

  it("resumes from a fresh stash after a sign-in round trip and removes it at once", async () => {
    window.history.replaceState(null, "", "/invite");
    stash("stashed-invite");
    const fetcher = routeFetch({
      [INSPECT]: () => json(existingInvite),
      [PROVIDERS]: () => json(google),
      [ME]: () => json({ id: "u1", email: "jesse@example.com" }),
    });
    render(
      <StrictMode>
        <InvitePage />
      </StrictMode>,
    );
    await screen.findByRole("button", { name: "Accept invite" });
    const inspectCall = fetcher.mock.calls.find(
      ([input]) => pathOf(input) === INSPECT,
    );
    expect(JSON.parse(inspectCall?.[1]?.body as string)).toEqual({
      token: "stashed-invite",
    });
    expect(window.sessionStorage.getItem(STASH_KEY)).toBeNull();
    expect(screen.queryByText(/Missing invite token/)).toBeNull();
  });

  it("ignores and removes a stash older than ten minutes", async () => {
    window.history.replaceState(null, "", "/invite");
    stash("stale-invite", Date.now() - TEN_MINUTES_MS - 1000);
    const fetcher = rs.spyOn(globalThis, "fetch");
    render(<InvitePage />);
    await screen.findByText(/Missing invite token/);
    expect(fetcher).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem(STASH_KEY)).toBeNull();
  });

  it("ignores and removes a stash that is not a timestamped token", async () => {
    window.history.replaceState(null, "", "/invite");
    window.sessionStorage.setItem(STASH_KEY, "bare-token");
    const fetcher = rs.spyOn(globalThis, "fetch");
    render(<InvitePage />);
    await screen.findByText(/Missing invite token/);
    expect(fetcher).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem(STASH_KEY)).toBeNull();
  });

  it("prefers the link's own token and clears a leftover stash", async () => {
    window.history.replaceState(null, "", "/invite#token=fresh-link");
    stash("older-invite");
    const fetcher = routeFetch({
      [INSPECT]: () => json(newInvite),
      [PROVIDERS]: () => json({ providers: [] }),
    });
    render(<InvitePage />);
    await screen.findByLabelText("New password");
    const inspectCall = fetcher.mock.calls.find(
      ([input]) => pathOf(input) === INSPECT,
    );
    expect(JSON.parse(inspectCall?.[1]?.body as string)).toEqual({
      token: "fresh-link",
    });
    expect(window.sessionStorage.getItem(STASH_KEY)).toBeNull();
  });

  it("offers Google as well as a password to a brand-new invitee", async () => {
    window.history.replaceState(null, "", "/invite#token=new-invite");
    routeFetch({
      [INSPECT]: () => json(newInvite),
      [PROVIDERS]: () => json(google),
    });
    render(<InvitePage />);
    await screen.findByLabelText("New password");
    await screen.findByRole("button", { name: "Continue with Google" });
    screen.getByText("Or skip the password: sign in with jesse@example.com.");
    // A new invitee creates a password here; there is none to sign in with.
    expect(
      screen.queryByRole("link", { name: "Sign in with password" }),
    ).toBeNull();
  });

  it("posts a new invitee's password with the token", async () => {
    window.history.replaceState(null, "", "/invite#token=new-invite");
    const fetcher = routeFetch({
      [INSPECT]: () => json(newInvite),
      [PROVIDERS]: () => json({ providers: [] }),
      [ACCEPT]: () => json({ detail: "Expired invitation" }, 403),
    });
    render(<InvitePage />);
    fireEvent.change(await screen.findByLabelText("New password"), {
      target: { value: "one-strong-password" },
    });
    fireEvent.change(screen.getByLabelText("Confirm password"), {
      target: { value: "one-strong-password" },
    });
    fireEvent.submit(
      screen.getByRole("button", { name: "Accept invite" }).closest("form")!,
    );
    await screen.findByText("Expired invitation");
    const acceptCall = fetcher.mock.calls.find(
      ([input]) => pathOf(input) === ACCEPT,
    );
    expect(JSON.parse(acceptCall?.[1]?.body as string)).toEqual({
      token: "new-invite",
      password: "one-strong-password",
    });
  });

  it("forgets a stashed token the server rejects", async () => {
    window.history.replaceState(null, "", "/invite");
    stash("dead-invite");
    routeFetch({
      [INSPECT]: () =>
        json({ detail: "Invitation is invalid or no longer available" }, 403),
    });
    render(<InvitePage />);
    await screen.findByText("Invitation is invalid or no longer available");
    await waitFor(() =>
      expect(window.sessionStorage.getItem(STASH_KEY)).toBeNull(),
    );
  });
});
