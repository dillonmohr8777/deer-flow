import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
} from "@testing-library/react";
import type { ReactNode } from "react";

import { SidebarProvider, useSidebar } from "@/components/ui/sidebar";
import { useSidebarExpanded } from "@/components/workspace/use-sidebar-expanded";
import { WorkspaceSidebarNavigation } from "@/components/workspace/workspace-sidebar-navigation";
import { WorkspaceSidebarTrigger } from "@/components/workspace/workspace-sidebar-trigger";

const navigation = rs.hoisted(() => ({
  pathname: "/workspace/chats/new",
  search: "",
}));

rs.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
  useSearchParams: () => new URLSearchParams(navigation.search),
}));

type HappyDOMWindow = typeof window & {
  happyDOM: { setViewport: (viewport: { width?: number }) => void };
};

function setViewportWidth(width: number) {
  (window as HappyDOMWindow).happyDOM.setViewport({ width });
}

function SidebarControls() {
  const { openMobile, setOpenMobile } = useSidebar();
  return (
    <>
      <button onClick={() => setOpenMobile(true)}>Open mobile drawer</button>
      <output data-testid="mobile-open">{String(openMobile)}</output>
    </>
  );
}

function NavigationTree() {
  return (
    <SidebarProvider defaultOpen={false}>
      <SidebarControls />
      <WorkspaceSidebarNavigation />
    </SidebarProvider>
  );
}

afterEach(() => {
  cleanup();
  setViewportWidth(1024);
  navigation.pathname = "/workspace/chats/new";
  navigation.search = "";
  rs.restoreAllMocks();
});

describe("workspace sidebar behavior", () => {
  it("treats the sidebar as expanded on mobile and honors the collapsed desktop state", () => {
    const wrapper = ({ children }: { children: ReactNode }) => (
      <SidebarProvider defaultOpen={false}>{children}</SidebarProvider>
    );

    setViewportWidth(1024);
    expect(
      renderHook(() => useSidebarExpanded(), { wrapper }).result.current,
    ).toBe(false);
    cleanup();

    setViewportWidth(390);
    expect(
      renderHook(() => useSidebarExpanded(), { wrapper }).result.current,
    ).toBe(true);
  });

  it("uses the mobile drawer state for its trigger icon", () => {
    setViewportWidth(390);
    render(
      <SidebarProvider defaultOpen={false}>
        <WorkspaceSidebarTrigger />
      </SidebarProvider>,
    );

    const trigger = screen.getByRole("button", { name: "Toggle Sidebar" });
    expect(
      trigger
        .querySelector("svg")
        ?.classList.contains("lucide-panel-left-open"),
    ).toBe(true);
    fireEvent.click(trigger);
    expect(
      trigger
        .querySelector("svg")
        ?.classList.contains("lucide-panel-left-close"),
    ).toBe(true);
  });

  it("keeps the drawer open for automatic new-chat thread assignment", () => {
    setViewportWidth(390);
    const view = render(<NavigationTree />);
    fireEvent.click(screen.getByRole("button", { name: "Open mobile drawer" }));
    expect(screen.getByTestId("mobile-open").textContent).toBe("true");

    act(() => {
      navigation.pathname = "/workspace/chats/thread-1";
      view.rerender(<NavigationTree />);
    });

    expect(screen.getByTestId("mobile-open").textContent).toBe("true");
  });

  it("closes the drawer after a query-only location change", () => {
    setViewportWidth(390);
    const view = render(<NavigationTree />);
    fireEvent.click(screen.getByRole("button", { name: "Open mobile drawer" }));

    act(() => {
      navigation.search = "source=back";
      view.rerender(<NavigationTree />);
    });

    expect(screen.getByTestId("mobile-open").textContent).toBe("false");
  });
});
