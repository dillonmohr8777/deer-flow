import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { SettingsDialog } from "@/components/workspace/settings/settings-dialog";
import { AuthProvider } from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";
import { enUS } from "@/core/i18n/locales/en-US";

rs.mock("next/dynamic", () => ({ default: () => () => null }));
rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
  usePathname: () => "/workspace",
}));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));

afterEach(cleanup);

const nav = () => screen.getByRole("navigation", { name: enUS.settings.title });
const current = () =>
  Array.from(nav().querySelectorAll('[aria-current="page"]'));

function renderDialog(
  props: Partial<React.ComponentProps<typeof SettingsDialog>> = {},
  role: User["system_role"] = "user",
) {
  return render(
    <AuthProvider
      initialUser={{
        id: "u1",
        email: "u@example.test",
        system_role: role,
        needs_setup: false,
      }}
    >
      <SettingsDialog open {...props} />
    </AuthProvider>,
  );
}

describe("settings dialog highlight", () => {
  it("focuses the selected section on open, not the first item", async () => {
    renderDialog({ defaultSection: "appearance" });
    const appearance = await screen.findByRole("button", {
      name: enUS.settings.sections.appearance,
    });
    expect(current()).toEqual([appearance]);
    expect(document.activeElement).toBe(appearance);
  });

  it("keeps exactly one selected item after switching", async () => {
    renderDialog({ defaultSection: "account" });
    const memory = await screen.findByRole("button", {
      name: enUS.settings.sections.memory,
    });
    fireEvent.click(memory);
    expect(current()).toEqual([memory]);
  });
});

describe("settings sections by role", () => {
  const names = () =>
    Array.from(nav().querySelectorAll("button")).map((b) => b.textContent);

  it("gives a client account, security, appearance, notifications and About only", async () => {
    renderDialog({ defaultSection: "appearance" }, "client");
    await screen.findByRole("button", {
      name: enUS.settings.sections.appearance,
    });
    expect(names()).toEqual([
      enUS.settings.sections.account,
      enUS.settings.sections.security,
      enUS.settings.sections.appearance,
      enUS.settings.sections.notification,
      enUS.settings.sections.about,
    ]);
  });

  it("falls back to appearance when a client deep links to an admin section", async () => {
    renderDialog({ defaultSection: "models" }, "client");
    const appearance = await screen.findByRole("button", {
      name: enUS.settings.sections.appearance,
    });
    expect(current()).toEqual([appearance]);
  });

  it.each(["admin", "exec", "user"] as const)(
    "keeps every section for a %s",
    async (role) => {
      renderDialog({ defaultSection: "appearance" }, role);
      await screen.findByRole("button", {
        name: enUS.settings.sections.appearance,
      });
      expect(names()).toHaveLength(12);
      expect(names()).toContain(enUS.settings.sections.models);
      expect(names()).toContain(enUS.settings.sections.channels);
    },
  );
});
