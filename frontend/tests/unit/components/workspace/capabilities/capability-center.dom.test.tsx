import { afterEach, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";
import type { PropsWithChildren } from "react";

const mocks = rs.hoisted(() => ({ search: "" }));

rs.mock("next/navigation", () => ({
  usePathname: () => "/workspace/capabilities",
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
  useSearchParams: () => new URLSearchParams(mocks.search),
}));

// The galleries fetch; this test is about the tab structure around them.
rs.mock("next/dynamic", () => ({
  default: () =>
    function Gallery() {
      return <div data-testid="gallery" />;
    },
}));

rs.mock("@/components/ui/sidebar", () => ({
  SidebarTrigger: () => null,
}));

import { CapabilityCenter } from "@/components/workspace/capabilities/capability-center";
import { I18nProvider } from "@/core/i18n/context";

function Wrapper({ children }: PropsWithChildren) {
  return <I18nProvider initialLocale="en-US">{children}</I18nProvider>;
}

afterEach(() => {
  cleanup();
  mocks.search = "";
});

for (const [search, name] of [
  ["", "Tools & integrations"],
  ["tab=skills", "Skills"],
  ["tab=extensions", "Extensions"],
] as const) {
  it(`gives the selected ${name} tab a panel its aria-controls resolves to`, () => {
    mocks.search = search;
    render(<CapabilityCenter />, { wrapper: Wrapper });
    const tab = screen.getByRole("tab", { name, selected: true });
    const panelId = tab.getAttribute("aria-controls");
    expect(panelId).toBeTruthy();
    const panel = document.getElementById(panelId!);
    expect(panel?.getAttribute("role")).toBe("tabpanel");
    expect(panel?.querySelector('[data-testid="gallery"]')).not.toBeNull();
  });
}
