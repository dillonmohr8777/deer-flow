import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { SidebarProvider } from "@/components/ui/sidebar";
import { WorkspaceHeader } from "@/components/workspace/workspace-container";
import { DEFAULT_LOCALE } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";

const nav = rs.hoisted(() => ({ pathname: "/workspace/scheduled-tasks" }));

rs.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}));

// The header's Background work icon has its own test; keep this one about labels.
rs.mock("@/components/workspace/command-center/background-jobs", () => ({
  BackgroundJobs: () => null,
}));

afterEach(() => {
  cleanup();
});

describe("workspace breadcrumb", () => {
  it.each([
    ["/workspace/scheduled-tasks", "Scheduled tasks"],
    ["/workspace/projects/p-1", "Projects"],
    ["/workspace/trash", "Trash"],
    ["/workspace/chats", "Chats"],
    ["/workspace/some-new_section", "Some new section"],
  ])("labels %s as %s, never as a raw slug", (pathname, label) => {
    nav.pathname = pathname;
    render(
      <I18nProvider initialLocale={DEFAULT_LOCALE}>
        <SidebarProvider>
          <WorkspaceHeader />
        </SidebarProvider>
      </I18nProvider>,
    );
    expect(screen.getByText(label)).toBeDefined();
    expect(screen.getByRole("banner").textContent).not.toMatch(/[a-z][-_][a-z]/i);
  });
});
