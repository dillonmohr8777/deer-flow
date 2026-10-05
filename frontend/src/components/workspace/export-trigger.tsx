"use client";

import {
  CalendarClock,
  Download,
  Ellipsis,
  FileJson,
  FileText,
} from "lucide-react";
import Link from "next/link";
import { useCallback } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
import { exportThread, type ThreadExportFormat } from "@/core/threads/export";
import type { AgentThread } from "@/core/threads/types";
import { useIsMobile } from "@/hooks/use-mobile";

import { useThread } from "./messages/context";
import { Tooltip } from "./tooltip";

/**
 * On phones the header can't hold every thread control at 44px beside a
 * readable title, so the thread's Scheduled tasks link (`scheduledTasksHref`)
 * folds into this menu and the menu becomes "Chat actions".
 */
export function ExportTrigger({
  threadId,
  scheduledTasksHref,
}: {
  threadId: string;
  scheduledTasksHref?: string;
}) {
  const { t } = useI18n();
  const { thread } = useThread();
  const isMobile = useIsMobile();
  const foldedHref = isMobile ? scheduledTasksHref : undefined;

  const messages = thread.messages;

  const handleExport = useCallback(
    (format: ThreadExportFormat) => {
      if (messages.length === 0) {
        toast.error(t.conversation.noMessages);
        return;
      }
      try {
        const agentThread = {
          thread_id: threadId,
          updated_at: new Date().toISOString(),
          values: thread.values,
        } as AgentThread;

        exportThread(agentThread, messages, format);
        toast.success(t.common.exportSuccess);
      } catch {
        toast.error(t.common.exportFailed);
      }
    },
    [messages, thread.values, threadId, t],
  );

  const canExport = messages.length > 0;
  if (!canExport && !foldedHref) {
    return null;
  }
  const label = foldedHref ? t.common.chatActions : t.common.export;

  return (
    <DropdownMenu>
      <Tooltip content={label}>
        <DropdownMenuTrigger asChild>
          <Button
            aria-label={label}
            className="text-muted-foreground hover:text-foreground"
            data-testid="export-trigger"
            variant="ghost"
          >
            {foldedHref ? <Ellipsis /> : <Download />}
            <span className="hidden sm:inline">{label}</span>
          </Button>
        </DropdownMenuTrigger>
      </Tooltip>
      <DropdownMenuContent align="end">
        {foldedHref && (
          <DropdownMenuItem asChild>
            <Link href={foldedHref}>
              <CalendarClock className="text-muted-foreground" />
              <span>{t.sidebar.scheduledTasks}</span>
            </Link>
          </DropdownMenuItem>
        )}
        {canExport && (
          <>
            <DropdownMenuItem onSelect={() => handleExport("markdown")}>
              <FileText className="text-muted-foreground" />
              <span>{t.common.exportAsMarkdown}</span>
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => handleExport("json")}>
              <FileJson className="text-muted-foreground" />
              <span>{t.common.exportAsJSON}</span>
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
