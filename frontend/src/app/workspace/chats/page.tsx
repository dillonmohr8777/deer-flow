"use client";

import { ArchiveRestore, MessageSquarePlus } from "lucide-react";
import Link from "next/link";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  EmptyState,
  ErrorState,
  pageStyles,
  WorkingState,
} from "@/components/workspace/page-body";
import {
  ThreadChannelBadge,
  ThreadChannelIcon,
} from "@/components/workspace/thread-channel-source";
import { VirtualThreadList } from "@/components/workspace/thread-list-virtualizer";
import { useThreadArchiveAction } from "@/components/workspace/use-thread-archive-action";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import { useProjects } from "@/core/projects";
import { THREAD_SEARCH_FAILED_FALLBACK } from "@/core/threads/api";
import {
  dayGroupKey,
  dayGroupLabel,
  dayGroupStartingAt,
} from "@/core/threads/day-groups";
import { useInfiniteThreads } from "@/core/threads/hooks";
import { buildThreadListModel } from "@/core/threads/thread-list-model";
import {
  channelSourceOfThread,
  pathOfThread,
  projectIdOfThread,
  titleOfThread,
} from "@/core/threads/utils";
import { formatCompactStamp, toDateTimeAttr } from "@/core/utils/datetime";
import { env } from "@/env";
import { cn } from "@/lib/utils";

export default function ChatsPage() {
  const { t, locale } = useI18n();
  const [view, setView] = useState("active");
  const archived = view === "archived";
  const staticWebsite = env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true";
  const archiveAction = useThreadArchiveAction();
  const {
    data: infiniteThreads,
    error,
    isLoading,
    isError,
    refetch,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteThreads({ archived: staticWebsite ? undefined : archived });
  const threadListModel = useMemo(
    () => buildThreadListModel(infiniteThreads?.pages ?? []),
    [infiniteThreads?.pages],
  );
  const { threads } = threadListModel;
  // Rows name their project so chats that open with the same prompt can be
  // told apart; the lookup only runs when a loaded thread has a project.
  const anyThreadInProject = threads.some(
    (thread) => projectIdOfThread(thread) !== null,
  );
  const { data: activeProjects } = useProjects("active", {
    enabled: anyThreadInProject,
  });
  const { data: archivedProjects } = useProjects("archived", {
    enabled: anyThreadInProject,
  });
  const projectNames = useMemo(
    () =>
      new Map(
        [...(activeProjects ?? []), ...(archivedProjects ?? [])].map(
          (project) => [project.id, project.name],
        ),
      ),
    [activeProjects, archivedProjects],
  );
  const [search, setSearch] = useState("");
  const isSearching = search.trim().length > 0;

  useEffect(() => {
    document.title = `${t.pages.chats} (${t.pages.appName})`;
  }, [t.pages.chats, t.pages.appName]);

  const filteredThreads = useMemo(() => {
    return threads.filter((thread) => {
      return titleOfThread(thread).toLowerCase().includes(search.toLowerCase());
    });
  }, [threads, search]);

  // Sentinel-based auto load-more for the unfiltered list (issue #3482).
  // In search mode we deliberately do NOT auto-paginate, otherwise an empty
  // filtered view would keep the sentinel in the viewport and drain the
  // entire backend list one page at a time.  Searching falls back to an
  // explicit button so users can still reach older conversations on demand.
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const element = sentinelRef.current;
    if (!element || !hasNextPage || isSearching) {
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting && hasNextPage && !isFetchingNextPage) {
          void fetchNextPage();
        }
      },
      { rootMargin: "200px 0px 200px 0px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage, isSearching, view]);

  const showEmptyState =
    !isLoading &&
    !isError &&
    filteredThreads.length === 0 &&
    !isSearching &&
    !archived;
  // Search only earns its place once there are chats to search; while the
  // read is out, failed or came back empty it would be a field over nothing.
  const showSearch = threads.length > 0 || isSearching;
  // Search is ready once it appears, except on phones, where focusing it
  // would open the keyboard over the list. Only the first appearance takes
  // focus, so switching tabs later never steals it.
  const searchRef = useRef<HTMLInputElement | null>(null);
  const recentTabRef = useRef<HTMLButtonElement | null>(null);
  const searchFocused = useRef(false);
  useEffect(() => {
    if (!showSearch || searchFocused.current) return;
    searchFocused.current = true;
    if (!window.matchMedia("(max-width: 639px)").matches) {
      searchRef.current?.focus();
    }
  }, [showSearch]);
  // The server's own reason, unless it is just the generic fallback again.
  const errorDetail =
    error?.message && error.message !== THREAD_SEARCH_FAILED_FALLBACK
      ? error.message
      : undefined;

  return (
    <WorkspaceContainer>
      <WorkspaceHeader></WorkspaceHeader>
      <WorkspaceBody className={pageStyles.page}>
        <ScrollArea className="size-full">
          <Tabs
            value={view}
            onValueChange={setView}
            className="mx-auto w-full max-w-(--container-width-md) gap-3 px-4 pt-8 pb-8"
          >
            <header className="mb-3">
              <div className="flex items-center justify-between gap-4">
                <h1>{t.pages.chats}</h1>
                {/* The empty state carries its own New chat; one action per view. */}
                {!showEmptyState && (
                  <Button asChild className="max-sm:min-h-11">
                    <Link href="/workspace/chats/new">
                      <MessageSquarePlus />
                      {t.sidebar.newChat}
                    </Link>
                  </Button>
                )}
              </div>
              <p className={cn(pageStyles.lede, "mt-1")}>{t.chats.lede}</p>
            </header>
            {!staticWebsite && (
              <TabsList aria-label={t.pages.chats}>
                <TabsTrigger value="active" ref={recentTabRef}>
                  {t.chats.activeChats}
                </TabsTrigger>
                <TabsTrigger value="archived">
                  {t.chats.archivedChats}
                </TabsTrigger>
              </TabsList>
            )}
            {showSearch && (
              <Input
                type="search"
                className="h-12 w-full text-base sm:text-xl"
                placeholder={t.chats.searchChats}
                ref={searchRef}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            )}
            <TabsContent value={view} className="pt-1">
              {isLoading && (
                <WorkingState label={t.chats.loadingChats} className="py-6" />
              )}
              {isError && (
                <ErrorState
                  className="py-6"
                  message={t.chats.loadChatsFailed}
                  detail={errorDetail}
                  action={
                    <Button
                      variant="outline"
                      size="sm"
                      className="max-sm:min-h-11"
                      onClick={() => void refetch()}
                    >
                      {t.chats.retryLoadChats}
                    </Button>
                  }
                />
              )}
              {!isLoading &&
                !isError &&
                filteredThreads.length === 0 &&
                (showEmptyState ? (
                  <div role="status" className="px-2 py-6">
                    <EmptyState
                      momo="lead"
                      title={t.chats.noActiveChats}
                      action={
                        <Button asChild size="sm" className="max-sm:min-h-11">
                          <Link href="/workspace/chats/new">
                            <MessageSquarePlus />
                            {t.sidebar.newChat}
                          </Link>
                        </Button>
                      }
                    >
                      {t.chats.noActiveChatsHint}
                    </EmptyState>
                  </div>
                ) : isSearching ? (
                  <p
                    role="status"
                    className="text-muted-foreground p-8 text-center"
                  >
                    {t.chats.noMatchingChats}
                  </p>
                ) : (
                  <div role="status" className="px-2 py-6">
                    <EmptyState
                      momo="reliability"
                      title={t.chats.noArchivedChats}
                      action={
                        <Button
                          variant="outline"
                          size="sm"
                          className="max-sm:min-h-11"
                          onClick={() => {
                            setView("active");
                            // The clicked button unmounts with the view, so
                            // focus lands on the tab it switched to.
                            requestAnimationFrame(() =>
                              recentTabRef.current?.focus(),
                            );
                          }}
                        >
                          {t.chats.backToRecentChats}
                        </Button>
                      }
                    >
                      {t.chats.noArchivedChatsHint}
                    </EmptyState>
                  </div>
                ))}
              <VirtualThreadList
                estimateSize={76}
                items={filteredThreads}
                scrollParentSelector='[data-slot="scroll-area-viewport"]'
                renderItem={(thread, index) => {
                  const channelSource = channelSourceOfThread(thread);
                  const title = titleOfThread(thread);
                  const projectName = projectNames.get(
                    projectIdOfThread(thread) ?? "",
                  );
                  const stamp = formatCompactStamp(thread.updated_at, locale);
                  // Chats are filed under the day they were last touched, so
                  // a phone scroll reads as a ledger instead of one long run.
                  const group = dayGroupStartingAt(filteredThreads, index);
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
                      <div
                        className={cn(
                          "flex items-center gap-2 border-b",
                          pageStyles.slip,
                          index % 2 === 1 && pageStyles.slipAlt,
                        )}
                      >
                        <Link
                          className="group/chat-row min-w-0 flex-1 rounded-[inherit]"
                          href={pathOfThread(thread)}
                          title={title}
                        >
                          <div className="flex flex-col gap-2 p-4">
                            <div className="flex min-w-0 items-start gap-2">
                              <ThreadChannelIcon source={channelSource} />
                              <div className="line-clamp-2 min-w-0 flex-1 break-words group-focus-visible/chat-row:line-clamp-none">
                                {title}
                              </div>
                              <ThreadChannelBadge
                                source={channelSource}
                                className="hidden sm:inline-flex"
                              />
                            </div>
                            {(stamp ?? projectName) && (
                              <div className="text-muted-foreground truncate text-sm">
                                {stamp && (
                                  <time
                                    dateTime={toDateTimeAttr(thread.updated_at)}
                                  >
                                    {stamp}
                                  </time>
                                )}
                                {stamp && projectName && (
                                  <span aria-hidden="true"> · </span>
                                )}
                                {projectName && (
                                  <span className="text-foreground font-semibold">
                                    {projectName}
                                  </span>
                                )}
                              </div>
                            )}
                          </div>
                        </Link>
                        {archived && (
                          <Button
                            className="mr-4 shrink-0 max-sm:min-h-11"
                            variant="outline"
                            size="sm"
                            disabled={archiveAction.isPending}
                            onClick={() =>
                              archiveAction.setArchived(thread.thread_id, false)
                            }
                          >
                            <ArchiveRestore className="size-4" />
                            {t.chats.restoreChat}
                          </Button>
                        )}
                      </div>
                    </Fragment>
                  );
                }}
              />
              {hasNextPage && !isSearching && (
                <div
                  ref={sentinelRef}
                  aria-hidden="true"
                  className="h-px w-full"
                  data-testid="chats-page-sentinel"
                />
              )}
              {hasNextPage && isSearching && (
                <div className="flex justify-center p-4">
                  <Button
                    variant="outline"
                    onClick={() => void fetchNextPage()}
                    disabled={isFetchingNextPage}
                    data-testid="chats-page-load-more"
                  >
                    {isFetchingNextPage
                      ? t.chats.loadingMore
                      : t.chats.loadMoreToSearch}
                  </Button>
                </div>
              )}
            </TabsContent>
          </Tabs>
        </ScrollArea>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
