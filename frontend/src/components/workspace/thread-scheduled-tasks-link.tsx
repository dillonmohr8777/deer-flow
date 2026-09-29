import { CalendarClock } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import { useIsMobile } from "@/hooks/use-mobile";

export function threadScheduledTasksHref(threadId: string) {
  return `/workspace/scheduled-tasks?thread_id=${encodeURIComponent(threadId)}`;
}

/**
 * On phones this link lives in the header's Chat actions menu instead. Same
 * predicate as ExportTrigger's fold, so at no width (or zoom) is it in
 * neither place.
 */
export function ThreadScheduledTasksLink({ threadId }: { threadId: string }) {
  const { t } = useI18n();
  const isMobile = useIsMobile();
  if (isMobile) {
    return null;
  }
  return (
    <Button variant="outline" size="sm" asChild>
      <Link
        aria-label={t.sidebar.scheduledTasks}
        href={threadScheduledTasksHref(threadId)}
      >
        <CalendarClock />
        <span className="hidden sm:inline">{t.sidebar.scheduledTasks}</span>
      </Link>
    </Button>
  );
}
