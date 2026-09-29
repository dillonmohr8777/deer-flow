"use client";

import { ArchiveRestore, MessageSquarePlus } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState, pageStyles } from "@/components/workspace/page-body";
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
import { useInfiniteThreads } from "@/core/threads/hooks";
import { buildThreadListModel } from "@/core/threads/thread-list-model";
import {
  channelSourceOfThread,
  pathOfThread,
  projectIdOfThread,
  titleOfThread,
} from "@/core/threads/utils";
import { formatTimeAgo } from "@/core/utils/datetime";
import { env } from "@/env";
import { cn } from "@/lib/utils";

export default function ChatsPage() {
  const { t } = useI18n();
  const [view, setView] = useState("active");
  const archived = view === "archived";
  const staticWebsite = env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true";
  const archiveAction = useThreadArchiveAction();
  const {
    data: infiniteThreads,
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

  // Search is ready on arrival, except on phones, where focusing it would
  // open the keyboard over the list.
  const searchRef = useRef<HTMLInputElement | null>(null);
  useEffect(() => {
    if (!window.matchMedia("(max-width: 639px)").matches) {
      searchRef.current?.focus();
    }
  }, []);

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
                <TabsTrigger value="active">{t.chats.activeChats}</TabsTrigger>
                <TabsTrigger value="archived">
                  {t.chats.archivedChats}
                </TabsTrigger>
              </TabsList>
            )}
            <Input
              type="search"
              className="h-12 w-full text-base sm:text-xl"
              placeholder={t.chats.searchChats}
              ref={searchRef}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <TabsContent value={view} className="pt-1">
              {isError && (
                <div role="alert" className="p-4 text-center">
                  <p>{t.chats.loadChatsFailed}</p>
                  <Button variant="outline" onClick={() => void refetch()}>
                    {t.chats.retryLoadChats}
                  </Button>
                </div>
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
                ) : (
                  <p
                    role="status"
                    className="text-muted-foreground p-8 text-center"
                  >
                    {isSearching
                      ? t.chats.noMatchingChats
                      : t.chats.noArchivedChats}
                  </p>
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
                  return (
                    <div
                      key={thread.thread_id}
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
                          {(thread.updated_at ?? projectName) && (
                            <div className="text-muted-foreground truncate text-sm">
                              {thread.updated_at && (
                                <time dateTime={thread.updated_at}>
                                  {formatTimeAgo(thread.updated_at)}
                                </time>
                              )}
                              {thread.updated_at && projectName && (
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
