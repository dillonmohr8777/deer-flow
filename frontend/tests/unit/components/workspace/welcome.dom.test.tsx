import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { Welcome } from "@/components/workspace/welcome";
import { enUS } from "@/core/i18n/locales/en-US";

const mocks = rs.hoisted(() => ({ params: new URLSearchParams() }));

rs.mock("next/navigation", () => ({ useSearchParams: () => mocks.params }));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));

afterEach(cleanup);

// Emoji and platform pictograms are banned as identity (DESIGN.md).
const pictograph = /\p{Extended_Pictographic}/u;

describe("Welcome", () => {
  it("greets in plain ink with no emoji or upstream branding, in every mode", () => {
    for (const mode of ["ultra", "flash"] as const) {
      const { container, unmount } = render(<Welcome mode={mode} />);
      expect(
        screen.getByRole("heading", { name: enUS.welcome.greeting }),
      ).toBeDefined();
      expect(container.textContent).not.toMatch(pictograph);
      expect(container.textContent).not.toContain("DeerFlow");
      expect(container.querySelector("[style]")).toBeNull();
      unmount();
    }
  });

  it("keeps the skill greeting free of emoji", () => {
    mocks.params = new URLSearchParams("mode=skill");
    const { container } = render(<Welcome />);
    expect(
      screen.getByRole("heading", { name: enUS.welcome.createYourOwnSkill }),
    ).toBeDefined();
    expect(container.textContent).not.toMatch(pictograph);
  });
});
