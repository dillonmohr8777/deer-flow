import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import { SidebarProvider } from "@/components/ui/sidebar";
import { RoleRouteGuard } from "@/components/workspace/role-route-guard";
import { WorkspaceHeader } from "@/components/workspace/workspace-header";
import { WorkspaceNavChatList } from "@/components/workspace/workspace-nav-chat-list";
import { AuthProvider } from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";
import { DEFAULT_LOCALE } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";

const mocks = rs.hoisted(() => ({
  pathname: "/workspace/chats",
  replace: rs.fn(),
  desk: false,
  internal: false,
  openai: false,
  agents: true,
  brandKit: true,
}));

rs.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname,
  useRouter: () => ({
    push: rs.fn(),
    replace: mocks.replace,
    refresh: rs.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}));
rs.mock("@/core/features", () => ({
  useDeskEnabled: () => ({ enabled: mocks.desk, isLoading: false }),
  useMomentumInternalEnabled: () => ({
    enabled: mocks.internal,
    isLoading: false,
  }),
  useOpenAIAgentsConfigured: () => ({
    configured: mocks.openai,
    isLoading: false,
  }),
}));
rs.mock("@/core/agents", () => ({
  useAgentsApiEnabled: () => ({ enabled: mocks.agents, isLoading: false }),
}));
rs.mock("@/core/board", () => ({ useBoardThreads: () => ({ data: [] }) }));
rs.mock("@/core/momobot-brand", () => ({
  useBrandKit: () => ({ data: mocks.brandKit ? { agents: [] } : undefined }),
}));

function user(role: User["system_role"]): User {
  return { id: "u1", email: "u@example.test", system_role: role } as User;
}

function renderAs(role: User["system_role"], children: ReactNode) {
  return render(
    <I18nProvider initialLocale={DEFAULT_LOCALE}>
      <AuthProvider initialUser={user(role)}>
        <SidebarProvider>{children}</SidebarProvider>
      </AuthProvider>
    </I18nProvider>,
  );
}

function hrefs(container: HTMLElement) {
  return [...container.querySelectorAll("a")].map((a) =>
    a.getAttribute("href"),
  );
}

beforeEach(() => {
  mocks.pathname = "/workspace/chats";
  mocks.replace.mockClear();
  mocks.desk = false;
  mocks.internal = false;
  mocks.openai = false;
  mocks.agents = true;
  mocks.brandKit = true;
});
afterEach(cleanup);

describe("the client sidebar", () => {
  it("shows Chats, MomoBot Agents and About, and nothing internal", () => {
    // Even if the Gateway were to report every internal feature on.
    mocks.desk = true;
    mocks.internal = true;
    mocks.openai = true;
    const { container } = renderAs("client", <WorkspaceNavChatList />);
    expect(hrefs(container)).toEqual([
      "/workspace/chats",
      "/workspace/lineup",
      "/workspace/about",
    ]);
    for (const name of [
      "Approvals",
      "Command Center",
      "OpenAI crew",
      "Workflows",
      "Browser research",
      "Agents",
      "Scheduled tasks",
      "Capability Center",
      "The Momo Daily",
      "Board",
      "Team",
      "AI Academy",
    ]) {
      expect(screen.queryByText(name), name).toBeNull();
    }
  });

  it("drops the brand kit links when the server has none", () => {
    mocks.brandKit = false;
    const { container } = renderAs("client", <WorkspaceNavChatList />);
    expect(hrefs(container)).toEqual(["/workspace/chats"]);
  });

  it("sends New chat and the logo to the chat with MomoBot Max", () => {
    const { container } = renderAs("client", <WorkspaceHeader />);
    const links = hrefs(container);
    expect(links).toContain("/workspace/agents/momobot-max/chats/new");
    expect(links).not.toContain("/workspace/command-center");
    expect(links).not.toContain("/workspace/chats/new");
  });
});

describe("the internal sidebar", () => {
  it.each(["admin", "exec", "user"] as const)(
    "keeps the short staff list for a %s",
    (role) => {
      const { container } = renderAs(role, <WorkspaceNavChatList />);
      const links = hrefs(container);
      for (const href of [
        "/workspace/approvals",
        "/workspace/scheduled-tasks",
        "/workspace/chats",
      ]) {
        expect(links, href).toContain(href);
      }
      // Command Center and Agents are admin-only.
      for (const href of ["/workspace/command-center", "/workspace/agents"]) {
        if (role === "admin") expect(links, href).toContain(href);
        else expect(links, href).not.toContain(href);
      }
    },
  );

  it("starts a new chat the usual way and keeps the Command Center logo", () => {
    const { container } = renderAs("admin", <WorkspaceHeader />);
    const links = hrefs(container);
    expect(links).toContain("/workspace/chats/new");
    expect(links).toContain("/workspace/command-center");
  });
});

describe("opening an internal page directly", () => {
  it("shows a client a polite not available page with a way back", () => {
    mocks.pathname = "/workspace/command-center";
    renderAs(
      "client",
      <RoleRouteGuard>
        <p>Internal dashboard</p>
      </RoleRouteGuard>,
    );
    expect(screen.queryByText("Internal dashboard")).toBeNull();
    expect(screen.getByText("This page isn't available")).toBeDefined();
    const back = screen.getByRole("link", { name: "Back to chat" });
    expect(back.getAttribute("href")).toBe(
      "/workspace/agents/momobot-max/chats/new",
    );
  });

  it.each([
    "/workspace/chats",
    "/workspace/chats/t-1",
    "/workspace/agents/momobot-max/chats/new",
    "/workspace/lineup",
    "/workspace/about",
  ])("lets a client open %s", (path) => {
    mocks.pathname = path;
    renderAs(
      "client",
      <RoleRouteGuard>
        <p>Chat page</p>
      </RoleRouteGuard>,
    );
    expect(screen.getByText("Chat page")).toBeDefined();
    expect(mocks.replace).not.toHaveBeenCalled();
  });

  it("moves a client from a new default chat to the chat with MomoBot Max", () => {
    mocks.pathname = "/workspace/chats/new";
    renderAs(
      "client",
      <RoleRouteGuard>
        <p>Default chat</p>
      </RoleRouteGuard>,
    );
    expect(screen.queryByText("Default chat")).toBeNull();
    expect(mocks.replace).toHaveBeenCalledWith(
      "/workspace/agents/momobot-max/chats/new",
    );
  });

  it.each(["admin", "exec", "user"] as const)("never blocks a %s", (role) => {
    mocks.pathname = "/workspace/command-center";
    renderAs(
      role,
      <RoleRouteGuard>
        <p>Internal dashboard</p>
      </RoleRouteGuard>,
    );
    expect(screen.getByText("Internal dashboard")).toBeDefined();
  });
});
