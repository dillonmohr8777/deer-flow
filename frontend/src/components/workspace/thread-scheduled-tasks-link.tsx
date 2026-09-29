import { CalendarClock } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";

export function threadScheduledTasksHref(threadId: string) {
  return `/workspace/scheduled-tasks?thread_id=${encodeURIComponent(threadId)}`;
}

/** Below 768px this link lives in the header's Chat actions menu instead. */
export function ThreadScheduledTasksLink({ threadId }: { threadId: string }) {
  const { t } = useI18n();
  return (
    <Button variant="outline" size="sm" className="max-md:hidden" asChild>
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
