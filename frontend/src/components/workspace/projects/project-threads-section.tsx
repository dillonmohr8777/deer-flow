"use client";

import Link from "next/link";
import { Fragment } from "react";

import { Button } from "@/components/ui/button";
import {
  EmptyState,
  ErrorState,
  pageStyles,
  WorkingState,
} from "@/components/workspace/page-body";
import { VirtualThreadList } from "@/components/workspace/thread-list-virtualizer";
import { useI18n } from "@/core/i18n/hooks";
import { type ProjectThreadsQueryResult } from "@/core/projects";
import {
  dayGroupKey,
  dayGroupLabel,
  dayGroupStartingAt,
} from "@/core/threads/day-groups";
import { pathOfThread } from "@/core/threads/utils";
import { formatCompactStamp } from "@/core/utils/datetime";
import { cn } from "@/lib/utils";

export function ProjectThreadsSection({
  query,
}: {
  query: ProjectThreadsQueryResult;
}) {
  const { t, locale } = useI18n();
  const threads = query.data?.pages.flatMap((page) => page) ?? [];
  return (
    // The Chats tab already names this panel; no second "Chats" heading.
    <section className="flex flex-col gap-2">
      {query.isError ? (
        <ErrorState
          message={t.projects.threadsLoadFailed}
          action={
            <Button
              variant="outline"
              size="sm"
              onClick={() => void query.refetch()}
            >
              {t.common.tryAgain}
            </Button>
          }
        />
      ) : query.isLoading ? (
        <WorkingState label={t.common.loading} />
      ) : threads.length === 0 ? (
        <EmptyState momo="lead" title={t.projects.empty}>
          {t.projects.interimMemoryNotice}
        </EmptyState>
      ) : (
        <div>
          {/* The page scrolls inside its own ScrollArea; the list windows rows
              against that viewport so paging through a long-lived project
              never grows unbounded DOM (same windowing the sidebar and
              /workspace/chats use). Rows are filed like the Chats page: day
              labels, two-line titles, the time or day under each, and paper
              slips on the desk below 640px. */}
          <VirtualThreadList
            estimateSize={76}
            items={threads}
            scrollParentSelector='[data-slot="scroll-area-viewport"]'
            renderItem={(thread, index) => {
              const title = thread.display_name?.trim()
                ? thread.display_name
                : t.projects.untitled;
              const stamp = formatCompactStamp(thread.updated_at, locale);
              const group = dayGroupStartingAt(threads, index);
              return (
                <Fragment key={thread.thread_id}>
                  {group && (
                    <h2
                      className={cn(
                        pageStyles.dayLabel,
                        index === 0 && pageStyles.dayLabelFirst,
                      )}
                      data-day-group={dayGroupKey(group)}
                    >
                      {dayGroupLabel(group, t.chats.dayGroups, locale)}
                    </h2>
                  )}
                  <Link
                    className={cn(
                      "group/chat-row hover:bg-accent flex min-w-0 flex-col gap-2 border-b p-4 transition-colors",
                      pageStyles.slip,
                      index % 2 === 1 && pageStyles.slipAlt,
                    )}
                    href={pathOfThread({
                      thread_id: thread.thread_id,
                      metadata: thread.metadata,
                    })}
                    title={title}
                  >
                    <span className="line-clamp-2 min-w-0 break-words group-focus-visible/chat-row:line-clamp-none">
                      {title}
                    </span>
                    {stamp && (
                      <time
                        className="text-muted-foreground text-sm"
                        dateTime={thread.updated_at}
                      >
                        {stamp}
                      </time>
                    )}
                  </Link>
                </Fragment>
              );
            }}
          />
        </div>
      )}
      {query.hasNextPage && (
        <Button
          variant="ghost"
          size="sm"
          className="justify-center text-xs max-sm:min-h-11"
          onClick={() => void query.fetchNextPage()}
          disabled={query.isFetchingNextPage}
          data-testid="project-threads-load-more"
        >
          {query.isFetchingNextPage
            ? t.chats.loadingMore
            : t.chats.loadOlderChats}
        </Button>
      )}
    </section>
  );
}
