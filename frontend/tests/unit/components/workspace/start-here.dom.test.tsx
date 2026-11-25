import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import { StartHereAcademyBody } from "@/components/workspace/start-here/start-here";
import { BUSINESS_OWNER_LESSONS } from "@/components/workspace/start-here/start-here-data";
import { AuthProvider } from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";

const featureState = rs.hoisted(() => ({ internal: false }));
const workspaceState = rs.hoisted(() => ({
  active_workspace_id: "ws-amp",
  isLoading: false,
  workspaces: [
    { id: "ws-amp", name: "AI Marketing Philly", role: "owner" },
    { id: "ws-other", name: "Other Workspace", role: "member" },
  ],
}));

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
  usePathname: () => "/workspace/start-here",
  useSearchParams: () => new URLSearchParams(),
}));

rs.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: ReactNode;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

rs.mock("@/core/agents/hooks", () => ({
  useAgents: () => ({
    agents: [{ name: "momobot-max", builtin: true }],
    isLoading: false,
  }),
}));

rs.mock("@/core/features", () => ({
  useMomentumInternalEnabled: () => ({
    enabled: featureState.internal,
    isLoading: false,
  }),
}));

rs.mock("@/core/workspaces/hooks", () => ({
  useWorkspaceSelection: () => ({
    data: workspaceState.isLoading
      ? undefined
      : {
          active_workspace_id: workspaceState.active_workspace_id,
          workspaces: workspaceState.workspaces,
        },
    isLoading: workspaceState.isLoading,
    busy: false,
    error: null,
    selectWorkspace: rs.fn(),
  }),
}));

function renderStartHere(role: User["system_role"] = "client") {
  return render(
    <AuthProvider
      initialUser={
        { id: "u-sh", email: "fixture-owner", system_role: role } as User
      }
    >
      <StartHereAcademyBody />
    </AuthProvider>,
  );
}

beforeEach(() => {
  featureState.internal = false;
  workspaceState.active_workspace_id = "ws-amp";
  workspaceState.isLoading = false;
  window.localStorage.clear();
});

afterEach(cleanup);

describe("Start Here / Academy", () => {
  it("renders in the AI Marketing Philly workspace, persists workspace-scoped completion, and filters prompts", () => {
    renderStartHere("client");

    expect(
      screen.getByRole("heading", { name: "Start Here / Academy" }),
    ).toBeTruthy();
    expect(
      screen.getByText("AI Marketing Philly · Business Owner Track"),
    ).toBeTruthy();
    expect(
      screen.getByText(
        `0 of ${BUSINESS_OWNER_LESSONS.length} quick-start lessons done`,
      ),
    ).toBeTruthy();

    // Never leaks internal staff Academy link to client role
    expect(
      screen.queryByRole("link", { name: /Staff AI Academy/i }),
    ).toBeNull();

    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[0]!);
    expect(
      screen.getByText(
        `1 of ${BUSINESS_OWNER_LESSONS.length} quick-start lessons done`,
      ),
    ).toBeTruthy();
    expect(screen.getByText("20%")).toBeTruthy();

    // Persists under the active workspace scope
    const stored = window.localStorage.getItem(
      "momobot.start-here.lessons.u-sh.ws-amp",
    );
    expect(stored).toContain('"control-panel-vs-chat":true');

    // Filter prompt library by Paid Ads
    fireEvent.click(screen.getByRole("button", { name: "Paid Ads" }));
    expect(
      screen.getByText("Local Google Ads Campaign Blueprint"),
    ).toBeTruthy();
    expect(screen.queryByText("Homepage Conversion Redesign")).toBeNull();
  });

  it("stays accessible for non-staff user members in AI Marketing Philly even when internal flag is off", () => {
    featureState.internal = false;
    renderStartHere("user");

    expect(
      screen.getByRole("heading", { name: "Start Here / Academy" }),
    ).toBeTruthy();
    expect(
      screen.getByText("AI Marketing Philly · Business Owner Track"),
    ).toBeTruthy();
    expect(
      screen.queryByRole("link", { name: /Staff AI Academy/i }),
    ).toBeNull();
  });

  it("shows a Staff AI Academy shortcut for internal non-client users", () => {
    featureState.internal = true;
    renderStartHere("admin");
    const link = screen.getByRole("link", { name: /Staff AI Academy/i });
    expect(link.getAttribute("href")).toBe("/workspace/academy");
  });

  it("disables lesson completion checkboxes while workspace selection is loading", () => {
    workspaceState.isLoading = true;
    renderStartHere("client");
    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes[0]?.hasAttribute("disabled")).toBe(true);
    expect(window.localStorage.length).toBe(0);
  });
});
