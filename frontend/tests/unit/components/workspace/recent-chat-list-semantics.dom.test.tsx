import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";

import { SidebarProvider } from "@/components/ui/sidebar";
import { RecentChatList } from "@/components/workspace/recent-chat-list";
import { ThreadDeleteDialogProvider } from "@/components/workspace/thread-delete-dialog";
import { AuthProvider } from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";
import { DEFAULT_LOCALE } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";
import { INFINITE_THREADS_QUERY_KEY_PREFIX } from "@/core/threads/hooks";
import type { AgentThread } from "@/core/threads/types";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
  usePathname: () => "/workspace",
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}));

function makeThread(
  id: string,
  title: string,
  metadata: Record<string, unknown> = {},
): AgentThread {
  return {
    thread_id: id,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    status: "idle",
    metadata,
    values: { title },
  } as unknown as AgentThread;
}

const LONG_TITLE =
  "Pull the September leads for Omega Landscaping and flag the calls that never booked";

function renderList() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  queryClient.setQueryData(
    [...INFINITE_THREADS_QUERY_KEY_PREFIX, { archived: false }],
    {
      pages: [
        [
          makeThread("t1", "First chat"),
          makeThread("t2", LONG_TITLE, { deerflow_project_id: "p1" }),
        ],
      ],
      pageParams: [0],
    },
  );
  const project = { id: "p1", name: "Omega relaunch" };
  queryClient.setQueryData(["projects", { status: "active" }], [project]);
  queryClient.setQueryData(["projects", { status: "archived" }], []);
  return render(
    <I18nProvider initialLocale={DEFAULT_LOCALE}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider
          initialUser={
            { id: "u1", email: "u@example.test", system_role: "user" } as User
          }
        >
          <SidebarProvider>
            <ThreadDeleteDialogProvider>
              <RecentChatList />
            </ThreadDeleteDialogProvider>
          </SidebarProvider>
        </AuthProvider>
      </QueryClientProvider>
    </I18nProvider>,
  );
}

afterEach(() => {
  cleanup();
});

describe("RecentChatList", () => {
  it("renders rows as items of a real list (axe list and listitem)", async () => {
    const { container } = renderList();
    await screen.findByText("First chat");
    const items = [...container.querySelectorAll("li")];
    expect(items).toHaveLength(2);
    for (const item of items) {
      const parent = item.parentElement;
      const isList =
        parent?.tagName === "UL" ||
        parent?.tagName === "OL" ||
        parent?.getAttribute("role") === "list";
      expect(isList).toBe(true);
    }
    for (const list of container.querySelectorAll("ul, ol"))
      for (const child of list.children) expect(child.tagName).toBe("LI");
    expect(screen.getByRole("list").querySelectorAll("li")).toHaveLength(2);
  });

  it("drops the per-thread glyph that read as one identical dark dot", async () => {
    const { container } = renderList();
    await screen.findByText("First chat");
    expect(container.querySelector("svg[data-momentum-glyph]")).toBeNull();
  });

  it("gives titles two lines, the full title on hover and a date/project line", async () => {
    renderList();
    const title = await screen.findByText(LONG_TITLE);
    expect(title.className).toContain("line-clamp-2");
    expect(title.className).toContain(
      "group-focus-visible/thread-link:line-clamp-none",
    );
    const link = title.closest("a");
    expect(link?.getAttribute("title")).toBe(LONG_TITLE);
    const metas = screen.getAllByTestId("thread-row-meta");
    expect(metas).toHaveLength(2);
    for (const meta of metas) {
      expect(meta.querySelector("time")?.getAttribute("dateTime")).toBe(
        "2026-01-02T00:00:00Z",
      );
    }
    expect(metas[1]?.textContent).toContain("Omega relaunch");
    expect(metas[0]?.textContent).not.toContain("·");
  });
});
