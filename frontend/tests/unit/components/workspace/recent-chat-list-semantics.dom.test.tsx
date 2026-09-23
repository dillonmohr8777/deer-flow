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

function makeThread(id: string, title: string): AgentThread {
  return {
    thread_id: id,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    status: "idle",
    metadata: {},
    values: { title },
  } as unknown as AgentThread;
}

function renderList() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  queryClient.setQueryData(
    [...INFINITE_THREADS_QUERY_KEY_PREFIX, { archived: false }],
    {
      pages: [
        [makeThread("t1", "First chat"), makeThread("t2", "Second chat")],
      ],
      pageParams: [0],
    },
  );
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
});
