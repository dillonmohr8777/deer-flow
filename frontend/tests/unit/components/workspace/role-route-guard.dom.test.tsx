import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import { RoleRouteGuard } from "@/components/workspace/role-route-guard";

const state = rs.hoisted(() => ({
  path: "/workspace/chats/new",
  loading: true,
  unresolved: false,
  agents: [] as { name: string; builtin: boolean }[],
  replace: rs.fn(),
}));
rs.mock("next/navigation", () => ({
  usePathname: () => state.path,
  useRouter: () => ({ replace: state.replace }),
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useIsClient: () => true,
  useIsRoleUnresolved: () => state.unresolved,
}));
rs.mock("@/core/agents/hooks", () => ({
  useAgents: () => ({ agents: state.agents, isLoading: state.loading }),
}));
rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      common: {
        pageNotAvailableTitle: "Unavailable",
        backToChat: "Back",
        pageNotAvailableDescription: "Internal page",
      },
    },
  }),
}));
rs.mock("@/components/workspace/page-body", () => ({
  EmptyState: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));
afterEach(() => {
  cleanup();
  state.replace.mockClear();
  state.path = "/workspace/chats/new";
  state.loading = true;
  state.unresolved = false;
  state.agents = [];
});
describe("synthetic client tenant redirects", () => {
  for (const tenant of ["tenant-a", "tenant-b"]) {
    it(`waits for ${tenant}'s scoped list without rendering a default chat`, async () => {
      const view = render(
        <RoleRouteGuard>
          <div>chat content</div>
        </RoleRouteGuard>,
      );
      expect(screen.queryByText("chat content")).toBeNull();
      expect(state.replace).not.toHaveBeenCalled();
      state.agents = [{ name: tenant, builtin: false }];
      state.loading = false;
      view.rerender(
        <RoleRouteGuard>
          <div>chat content</div>
        </RoleRouteGuard>,
      );
      await waitFor(() =>
        expect(state.replace).toHaveBeenCalledWith(
          `/workspace/agents/${tenant}/chats/new`,
        ),
      );
      expect(screen.queryByText("chat content")).toBeNull();
    });
  }
  it("shows an owned legacy route while internal pages and unresolved roles stay hidden", () => {
    state.path = "/workspace/chats/legacy-owned";
    const view = render(
      <RoleRouteGuard>
        <div>legacy content</div>
      </RoleRouteGuard>,
    );
    expect(screen.getByText("legacy content")).toBeTruthy();
    state.path = "/workspace/approvals";
    view.rerender(
      <RoleRouteGuard>
        <div>internal data</div>
      </RoleRouteGuard>,
    );
    expect(screen.queryByText("internal data")).toBeNull();
    state.unresolved = true;
    state.path = "/workspace/chats/legacy-owned";
    view.rerender(
      <RoleRouteGuard>
        <div>legacy content</div>
      </RoleRouteGuard>,
    );
    expect(screen.queryByText("legacy content")).toBeNull();
  });
});
