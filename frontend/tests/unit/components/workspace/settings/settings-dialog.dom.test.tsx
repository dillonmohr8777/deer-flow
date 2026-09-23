import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { SettingsDialog } from "@/components/workspace/settings/settings-dialog";
import { enUS } from "@/core/i18n/locales/en-US";

rs.mock("next/dynamic", () => ({ default: () => () => null }));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));

afterEach(cleanup);

const nav = () => screen.getByRole("navigation", { name: enUS.settings.title });
const current = () =>
  Array.from(nav().querySelectorAll('[aria-current="page"]'));

describe("settings dialog highlight", () => {
  it("focuses the selected section on open, not the first item", async () => {
    render(<SettingsDialog open defaultSection="appearance" />);
    const appearance = await screen.findByRole("button", {
      name: enUS.settings.sections.appearance,
    });
    expect(current()).toEqual([appearance]);
    expect(document.activeElement).toBe(appearance);
  });

  it("keeps exactly one selected item after switching", async () => {
    render(<SettingsDialog open defaultSection="account" />);
    const memory = await screen.findByRole("button", {
      name: enUS.settings.sections.memory,
    });
    fireEvent.click(memory);
    expect(current()).toEqual([memory]);
  });
});
