import { describe, expect, it } from "@rstest/core";

import {
  inviteSignInMode,
  signedInAsInvitee,
  ssoStartUrl,
  type InviteInfo,
} from "@/app/invite/invite-mode";

const base: InviteInfo = {
  email: "jesse@example.com",
  workspace_name: "Momentum",
  expires_at: "2026-10-01T00:00:00Z",
  requires_login: false,
};

describe("invite sign-in mode", () => {
  it("uses the server's sign_in when present", () => {
    expect(
      inviteSignInMode({ ...base, sign_in: "sso", requires_login: true }),
    ).toBe("sso");
    expect(
      inviteSignInMode({ ...base, sign_in: "password", requires_login: true }),
    ).toBe("password");
    expect(inviteSignInMode({ ...base, sign_in: "new" })).toBe("new");
  });

  it("falls back to requires_login for an older Gateway", () => {
    expect(inviteSignInMode(base)).toBe("new");
    expect(inviteSignInMode({ ...base, requires_login: true })).toBe(
      "password",
    );
  });

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
});
