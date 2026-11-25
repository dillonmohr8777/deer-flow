import { describe, expect, it } from "@rstest/core";

import {
  isStaffRole,
  resolveCleanClientMode,
} from "@/core/settings/client-mode";

describe("Clean Client Mode resolution", () => {
  it("recognizes admin and exec as staff roles", () => {
    expect(isStaffRole({ system_role: "admin" })).toBe(true);
    expect(isStaffRole({ system_role: "exec" })).toBe(true);
    expect(isStaffRole({ system_role: "user" })).toBe(false);
    expect(isStaffRole({ system_role: "client" })).toBe(false);
    expect(isStaffRole(null)).toBe(false);
  });

  it("locks Clean Client Mode ON for client accounts even if show is requested", () => {
    expect(
      resolveCleanClientMode({
        user: { system_role: "client" },
        experienceMode: "hard",
        developerDetailsMode: "show",
      }),
    ).toBe(true);
  });

  it("defaults Clean Client Mode ON for non-staff user accounts and lets them toggle", () => {
    expect(
      resolveCleanClientMode({
        user: { system_role: "user" },
        experienceMode: "medium",
        developerDetailsMode: "auto",
      }),
    ).toBe(true);
    expect(
      resolveCleanClientMode({
        user: { system_role: "user" },
        experienceMode: "medium",
        developerDetailsMode: "show",
      }),
    ).toBe(false);
  });

  it("defaults Clean Client Mode OFF for admin/exec in medium/hard mode, and ON in easy mode or hide override", () => {
    expect(
      resolveCleanClientMode({
        user: { system_role: "admin" },
        experienceMode: "medium",
        developerDetailsMode: "auto",
      }),
    ).toBe(false);
    expect(
      resolveCleanClientMode({
        user: { system_role: "exec" },
        experienceMode: "hard",
        developerDetailsMode: "auto",
      }),
    ).toBe(false);
    expect(
      resolveCleanClientMode({
        user: { system_role: "admin" },
        experienceMode: "easy",
        developerDetailsMode: "auto",
      }),
    ).toBe(true);
    expect(
      resolveCleanClientMode({
        user: { system_role: "admin" },
        experienceMode: "hard",
        developerDetailsMode: "hide",
      }),
    ).toBe(true);
  });

  it("defaults OFF when user is null (static demo / unauthenticated tests)", () => {
    expect(
      resolveCleanClientMode({
        user: null,
        experienceMode: undefined,
        developerDetailsMode: "auto",
      }),
    ).toBe(false);
  });
});
