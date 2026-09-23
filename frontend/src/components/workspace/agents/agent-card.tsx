"use client";

import { MessageSquareIcon, Settings2Icon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { formatModelLabel } from "@/components/workspace/command-center/model-label";
import { MomoAvatar } from "@/components/workspace/command-center/momo-avatar";
import { pageStyles } from "@/components/workspace/page-body";
import { useDeleteAgent } from "@/core/agents";
import type { Agent } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";

import { AgentSettingsDialog } from "./agent-settings-dialog";

interface AgentCardProps {
  agent: Agent;
}

/**
 * One line of the roster: the agent's Momo, name and model, what it is for,
 * what it may use, and two actions. Chat is the one thing you do here;
 * settings (and delete, inside settings) stay one step back.
 */
export function AgentCard({ agent }: AgentCardProps) {
  const displayName = agent.display_name?.length
    ? agent.display_name
    : agent.name;
  const { t } = useI18n();
  const router = useRouter();
  const deleteAgent = useDeleteAgent();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const capabilities = [
    ...(agent.tool_groups ?? []).map((group) => `tg:${group}`),
    ...(agent.skills ?? []).map((skill) => `sk:${skill}`),
  ];

  function handleChat() {
    router.push(`/workspace/agents/${agent.name}/chats/new`);
  }

  async function handleDelete() {
    try {
      await deleteAgent.mutateAsync(agent.name);
      toast.success(t.agents.deleteSuccess);
      setDeleteOpen(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <li className="flex flex-wrap items-start gap-x-4 gap-y-3 py-5">
      {/* Same identity as the Command Center roster; the name is the row
          heading, so the mark is decorative here. */}
      <span aria-hidden="true" className="shrink-0">
        <MomoAvatar agent={agent} size={48} />
      </span>
      <div className="min-w-0 flex-1 basis-64">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
          <h2
            className="min-w-0 text-lg leading-6 font-semibold [overflow-wrap:anywhere]"
            title={displayName}
          >
            {displayName}
          </h2>
          {agent.model && (
            <span className="text-muted-foreground text-xs font-bold">
              {formatModelLabel(agent.model)}
            </span>
          )}
        </div>
        {agent.description && (
          <p
            className="text-muted-foreground mt-1 line-clamp-2 max-w-[68ch] text-sm leading-6"
            title={agent.description}
          >
            {agent.description}
          </p>
        )}
        {capabilities.length > 0 && (
          <ul className="mt-2.5 flex flex-wrap gap-1.5">
            {capabilities.map((key) => (
              <li key={key} className={pageStyles.chip} title={key.slice(3)}>
                {key.slice(3)}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="ml-auto flex shrink-0 items-center gap-1 pl-16 sm:pl-0">
        <Button size="sm" variant="outline" onClick={handleChat}>
          <MessageSquareIcon className="size-3.5" />
          {t.agents.chat}
          <span className="sr-only">{displayName}</span>
        </Button>
        <Button
          size="icon-sm"
          variant="ghost"
          onClick={() => setSettingsOpen(true)}
          title={t.agents.settings}
          aria-label={`${t.agents.settings}: ${displayName}`}
        >
          <Settings2Icon className="size-4" />
        </Button>
      </div>

      {/* Agent settings — mounted only while open so its form state always
          re-seeds from the latest agent props (avoids stale values on reopen). */}
      {settingsOpen && (
        <AgentSettingsDialog
          agent={agent}
          open={settingsOpen}
          onOpenChange={setSettingsOpen}
          onDelete={() => {
            setSettingsOpen(false);
            setDeleteOpen(true);
          }}
        />
      )}

      {/* Delete Confirm */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.agents.delete}</DialogTitle>
            <DialogDescription>{t.agents.deleteConfirm}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteOpen(false)}
              disabled={deleteAgent.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleteAgent.isPending}
            >
              {deleteAgent.isPending ? t.common.loading : t.common.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </li>
  );
}
