"use client";

import { PlusIcon } from "lucide-react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { SidebarTrigger } from "@/components/ui/sidebar";
import {
  EmptyState,
  ErrorState,
  pageStyles,
  WorkingState,
} from "@/components/workspace/page-body";
import { useAgents } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { AgentCard } from "./agent-card";

export function AgentGallery() {
  const { t } = useI18n();
  const { agents, isLoading, error, refetch } = useAgents();
  const router = useRouter();

  const handleNewAgent = () => {
    router.push("/workspace/agents/new");
  };

  return (
    <div
      className={cn("momentum-page flex size-full flex-col", pageStyles.page)}
    >
      {/* Page header. Agents has no WorkspaceHeader, so it carries the same
          phone-only sidebar trigger the other workspace pages do. */}
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3 border-b px-4 py-5 sm:px-8">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <SidebarTrigger className="-ml-2 md:hidden" />
            <h1 className="text-2xl">{t.agents.title}</h1>
          </div>
          <p className={cn(pageStyles.lede, "mt-1")}>{t.agents.description}</p>
        </div>
        <Button onClick={handleNewAgent}>
          <PlusIcon className="mr-1.5 h-4 w-4" />
          {t.agents.newAgent}
        </Button>
      </div>

      {/* Roster */}
      <div className="flex-1 overflow-y-auto px-4 pb-28 sm:px-8">
        <div className="mx-auto w-full max-w-5xl">
          {isLoading ? (
            <WorkingState label={t.common.loading} />
          ) : error ? (
            <ErrorState
              message={t.agents.loadFailed}
              detail={error.message}
              action={
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void refetch()}
                >
                  {t.common.tryAgain}
                </Button>
              }
            />
          ) : agents.length === 0 ? (
            <EmptyState
              momo="builder"
              title={t.agents.emptyTitle}
              action={
                <Button variant="outline" size="sm" onClick={handleNewAgent}>
                  <PlusIcon className="h-4 w-4" />
                  {t.agents.newAgent}
                </Button>
              }
            >
              {t.agents.emptyDescription}
            </EmptyState>
          ) : (
            <ul className={cn("divide-y", pageStyles.rows)}>
              {agents.map((agent) => (
                <AgentCard key={agent.name} agent={agent} />
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
