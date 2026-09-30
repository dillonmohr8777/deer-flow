import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render } from "@testing-library/react";
import type { PropsWithChildren } from "react";

import { ProjectThreadsSection } from "@/components/workspace/projects/project-threads-section";
import { I18nProvider } from "@/core/i18n/context";
import type { ProjectThreadsQueryResult } from "@/core/projects";
import type { ProjectThread } from "@/core/projects/types";

// Keep the row links inert under happy-dom; only the href wiring matters.
rs.mock("next/link", () => {
  const MockLink = ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
    className?: string;
    title?: string;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  );
  return { default: MockLink };
});

function makeThread(id: string, title: string): ProjectThread {
  return {
    thread_id: id,
    display_name: title,
    metadata: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
  };
}

function makeQuery(threads: ProjectThread[]): ProjectThreadsQueryResult {
  return {
    data: { pages: [threads], pageParams: [0] },
    isError: false,
    isLoading: false,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: rs.fn(),
  } as unknown as ProjectThreadsQueryResult;
}

function Wrapper({ children }: PropsWithChildren) {
  return <I18nProvider initialLocale="en-US">{children}</I18nProvider>;
}

afterEach(() => {
  cleanup();
});

describe("ProjectThreadsSection", () => {
  it("files chats like the Chats page: day labels, two-line titles, a time", () => {
    const now = new Date();
    const at = (daysAgo: number) => {
      const d = new Date(now);
      d.setDate(d.getDate() - daysAgo);
      d.setHours(9, 30, 0, 0);
      return d.toISOString();
    };
    const { container } = render(
      <Wrapper>
        <ProjectThreadsSection
          query={makeQuery([
            { ...makeThread("t-1", "First"), updated_at: at(0) },
            { ...makeThread("t-2", "Second"), updated_at: at(0) },
            { ...makeThread("t-3", "Third"), updated_at: at(1) },
          ])}
        />
      </Wrapper>,
    );

    const links = container.querySelectorAll<HTMLAnchorElement>("a");
    expect(links).toHaveLength(3);
    expect(links[0]?.href).toContain("/workspace/chats/t-1");
    // Every row carries its rule (no border-y frame to double the last one).
    for (const link of links) {
      expect(link.classList.contains("border-b")).toBe(true);
    }
    // A label opens each day, not each chat.
    const labels = [...container.querySelectorAll("h2")].map(
      (h) => h.textContent,
    );
    expect(labels).toEqual(["Today", "Yesterday"]);
    // Titles wrap to two lines and name themselves on hover.
    expect(links[0]?.getAttribute("title")).toBe("First");
    expect(links[0]?.querySelector(".line-clamp-2")?.textContent).toBe("First");
    // The time is a real <time>, today as a clock time.
    const time = links[0]?.querySelector("time");
    expect(time?.getAttribute("dateTime")).toBe(at(0));
    expect(time?.textContent).toMatch(/9:30/);
  });

  it("shows the untitled fallback and the load-more button for a partial page", () => {
    const { container } = render(
      <Wrapper>
        <ProjectThreadsSection
          query={
            {
              data: {
                pages: [[makeThread("t-1", "  ")]],
                pageParams: [0],
              },
              isError: false,
              isLoading: false,
              hasNextPage: true,
              isFetchingNextPage: false,
              fetchNextPage: rs.fn(),
            } as unknown as ProjectThreadsQueryResult
          }
        />
      </Wrapper>,
    );

    expect(container.textContent).toContain("Untitled");
    expect(
      container.querySelector('[data-testid="project-threads-load-more"]'),
    ).not.toBeNull();
  });
});
