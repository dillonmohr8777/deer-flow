/**
 * How the invite page asks the invited person to prove who they are. Kept
 * out of page.tsx so it can be unit tested and so the page file only
 * exports its component.
 */

export type InviteSignIn = "new" | "password" | "sso";

export type InviteInfo = {
  email: string;
  workspace_name: string;
  expires_at: string;
  requires_login: boolean;
  /** Absent on an older Gateway; fall back to requires_login. */
  sign_in?: InviteSignIn;
};

export function inviteSignInMode(info: InviteInfo): InviteSignIn {
  if (
    info.sign_in === "new" ||
    info.sign_in === "password" ||
    info.sign_in === "sso"
  ) {
    return info.sign_in;
  }
  return info.requires_login ? "password" : "new";
}

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
 * log. A sign-in round trip (Google and back) loses the fragment, so the
 * token waits in this tab's sessionStorage instead of in any URL.
 */
export const INVITE_TOKEN_STORAGE_KEY = "momobot.invite.token";

export function stashInviteToken(token: string): void {
  try {
    window.sessionStorage.setItem(INVITE_TOKEN_STORAGE_KEY, token);
  } catch {
    // Storage blocked: the person reopens the link from their DM instead.
  }
}

export function readStashedInviteToken(): string | null {
  try {
    return window.sessionStorage.getItem(INVITE_TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function clearStashedInviteToken(): void {
  try {
    window.sessionStorage.removeItem(INVITE_TOKEN_STORAGE_KEY);
  } catch {
    // Nothing to clear.
  }
}

/** Start an SSO sign-in that comes back to /invite (token stays stashed). */
export function ssoStartUrl(providerId: string): string {
  return `/api/v1/auth/oauth/${encodeURIComponent(providerId)}?next=${encodeURIComponent("/invite")}&remember_me=true`;
}
