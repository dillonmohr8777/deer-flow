import { describe, expect, it } from "@rstest/core";

import {
  INVITE_STASH_MAX_AGE_MS,
  parseInviteStash,
  passwordSignInUrl,
  serializeInviteStash,
  signedInAsInvitee,
  ssoStartUrl,
} from "@/app/invite/invite-mode";
import { validateAuthNextPath } from "@/core/auth/next-path";
import { buildLoginUrl } from "@/core/auth/types";

const NOW = Date.UTC(2026, 8, 25, 12, 0, 0);

describe("invite page helpers", () => {
  it("matches the session email to the invite, ignoring case and spaces", () => {
    expect(signedInAsInvitee(" Jesse@Example.com ", "jesse@example.com")).toBe(
      true,
    );
    expect(signedInAsInvitee("other@example.com", "jesse@example.com")).toBe(
      false,
    );
    expect(signedInAsInvitee(null, "jesse@example.com")).toBe(false);
    expect(signedInAsInvitee(undefined, "jesse@example.com")).toBe(false);
  });

  it("starts SSO with a return to /invite and never the token", () => {
    const url = ssoStartUrl("google");
    expect(url).toBe(
      "/api/v1/auth/oauth/google?next=%2Finvite&remember_me=true",
    );
    expect(url).not.toContain("token");
  });

  it("sends password sign-in to the login page the same way the app does", () => {
    const url = passwordSignInUrl();
    expect(url).toBe("/login?next=%2Finvite");
    expect(url).toBe(buildLoginUrl("/invite"));
    // The login page only honours a next path that passes this check.
    const next = new URLSearchParams(url.split("?")[1]).get("next");
    expect(validateAuthNextPath(next)).toBe("/invite");
    expect(url).not.toContain("token");
  });
});

describe("invite token stash", () => {
  it("round-trips a fresh stash", () => {
    const raw = serializeInviteStash("invite-token", NOW);
    expect(JSON.parse(raw)).toEqual({ token: "invite-token", savedAt: NOW });
    expect(parseInviteStash(raw, NOW)).toBe("invite-token");
    expect(parseInviteStash(raw, NOW + INVITE_STASH_MAX_AGE_MS)).toBe(
      "invite-token",
    );
  });

  it("ignores a stash older than ten minutes", () => {
    expect(INVITE_STASH_MAX_AGE_MS).toBe(10 * 60 * 1000);
    const raw = serializeInviteStash("invite-token", NOW);
    expect(parseInviteStash(raw, NOW + INVITE_STASH_MAX_AGE_MS + 1)).toBe(null);
  });

  it("ignores a stash that is malformed, from the future or a bare token", () => {
    for (const raw of [
      null,
      "",
      "bare-token-from-an-older-page",
      "null",
      "[]",
      JSON.stringify({ token: "", savedAt: NOW }),
      JSON.stringify({ token: "invite-token" }),
      JSON.stringify({ token: "invite-token", savedAt: "yesterday" }),
      JSON.stringify({ token: 42, savedAt: NOW }),
      serializeInviteStash("invite-token", NOW + 60_000),
    ]) {
      expect(parseInviteStash(raw, NOW)).toBe(null);
    }
  });
});
