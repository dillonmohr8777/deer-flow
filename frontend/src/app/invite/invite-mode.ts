/**
 * Helpers for the invite page, kept out of page.tsx so they can be unit
 * tested and so the page file only exports its component.
 */

export type InviteInfo = {
  email: string;
  workspace_name: string;
  expires_at: string;
  /**
   * The invited email already has an account. It signs in first (however it
   * signs in) and then accepts with its own session; it never types a
   * password into this page.
   */
  requires_login: boolean;
};

/** Whether the browser's session belongs to the invited email. */
export function signedInAsInvitee(
  sessionEmail: string | null | undefined,
  inviteEmail: string,
): boolean {
  return (
    !!sessionEmail &&
    sessionEmail.trim().toLowerCase() === inviteEmail.trim().toLowerCase()
  );
}

/**
 * The invite token rides in the URL fragment so it never reaches a server
 * log. A sign-in trip (Google, or the password login page) loses the
 * fragment, so right before leaving, the token waits in this tab's
 * sessionStorage (never in a URL or next=). The page reads and removes it on
 * load and keeps it only in React state from then on. A stash older than ten
 * minutes belongs to an abandoned sign-in and is ignored.
 */
export const INVITE_TOKEN_STORAGE_KEY = "momobot.invite.token";
export const INVITE_STASH_MAX_AGE_MS = 10 * 60 * 1000;

type InviteStash = { token: string; savedAt: number };

export function serializeInviteStash(token: string, savedAt: number): string {
  const stash: InviteStash = { token, savedAt };
  return JSON.stringify(stash);
}

/** The stashed token, or null when the value is malformed or stale. */
export function parseInviteStash(
  raw: string | null,
  now: number,
): string | null {
  if (!raw) return null;
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!value || typeof value !== "object") return null;
  const { token, savedAt } = value as Record<string, unknown>;
  if (typeof token !== "string" || token.length === 0) return null;
  if (typeof savedAt !== "number" || !Number.isFinite(savedAt)) return null;
  const age = now - savedAt;
  if (age < 0 || age > INVITE_STASH_MAX_AGE_MS) return null;
  return token;
}

export function stashInviteToken(token: string): void {
  try {
    window.sessionStorage.setItem(
      INVITE_TOKEN_STORAGE_KEY,
      serializeInviteStash(token, Date.now()),
    );
  } catch {
    // Storage blocked: after signing in, the person reopens the link instead.
  }
}

/** Read the stash and remove it in the same step, so it never lingers. */
export function takeStashedInviteToken(): string | null {
  let raw: string | null;
  try {
    raw = window.sessionStorage.getItem(INVITE_TOKEN_STORAGE_KEY);
    window.sessionStorage.removeItem(INVITE_TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
  return parseInviteStash(raw, Date.now());
}

export function clearStashedInviteToken(): void {
  try {
    window.sessionStorage.removeItem(INVITE_TOKEN_STORAGE_KEY);
  } catch {
    // Nothing to clear.
  }
}

/** Where a sign-in started from the invite page comes back to. */
export const INVITE_RETURN_PATH = "/invite";

/**
 * Password sign-in that comes back to /invite. Same shape as
 * `buildLoginUrl` in core/auth/types.ts (the unit test pins that), built
 * here so this public page does not bundle the zod user schema.
 */
export function passwordSignInUrl(): string {
  return `/login?next=${encodeURIComponent(INVITE_RETURN_PATH)}`;
}

/** Start an SSO sign-in that comes back to /invite. */
export function ssoStartUrl(providerId: string): string {
  return `/api/v1/auth/oauth/${encodeURIComponent(providerId)}?next=${encodeURIComponent(INVITE_RETURN_PATH)}&remember_me=true`;
}
