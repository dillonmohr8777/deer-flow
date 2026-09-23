"use client";

import { Clock3Icon } from "lucide-react";
import { useEffect, useState } from "react";

import { useI18n } from "@/core/i18n/hooks";
import { formatRunDuration } from "@/core/messages/run-duration";

import { WorkingSquares } from "./ultra-thinking";

export function RunActivity({ startTime }: { startTime: number | null }) {
  const { t } = useI18n();
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (startTime === null) {
      setElapsed(0);
      return;
    }

    const updateElapsed = () => {
      setElapsed(Math.max(0, Math.floor((Date.now() - startTime) / 1000)));
    };
    updateElapsed();
    const interval = setInterval(updateElapsed, 1000);
    return () => clearInterval(interval);
  }, [startTime]);

  const formatted = formatRunDuration(elapsed, t.runDuration);

  return (
    <div
      className="text-muted-foreground flex items-center gap-2 text-sm"
      data-testid="run-activity"
    >
      {/* Ticks in steps(3) over 1.2s; still under reduced motion. The word
          says it too, so the squares stay decoration. */}
      <WorkingSquares />
      <span>{t.runDuration.working}</span>
      {formatted && <span aria-hidden="true">({formatted})</span>}
    </div>
  );
}

export function RunDuration({ durationSeconds }: { durationSeconds: number }) {
  const { t } = useI18n();
  const formatted = formatRunDuration(durationSeconds, t.runDuration);
  if (!formatted) {
    return null;
  }

  return (
    <div
      className="text-muted-foreground flex items-center gap-2 text-sm"
      data-receipt=""
      data-testid="run-duration"
      title={t.runDuration.description}
    >
      <Clock3Icon className="size-4" />
      <span>{t.runDuration.completedIn(formatted)}</span>
    </div>
  );
}
