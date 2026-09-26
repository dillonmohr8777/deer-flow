"use client";

import { useEffect, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";

import { stampDate, type AgentLife, type AgentLifeState } from "./agent-life";

import styles from "./agent-alive.module.css";

/**
 * Wraps an agent's avatar so it shows the agent's recorded run state
 * (DESIGN.md, Motion item 7):
 *
 * - idle: still
 * - thinking: a slow paper tilt
 * - running: pinned, with a small sway from the pin
 * - done: a dated ink stamp, which lands once, and only when this view saw
 *   the run finish (loading a page with a finished run is not a change)
 * - failed: a torn corner, no motion
 * - unknown: still, like idle (no run in a truncated history page)
 *
 * `motion` is the workspace's brandMotionAllowed() result. paper.css also
 * gates the animations on `prefers-reduced-motion: no-preference`, so either
 * switch alone leaves the static state. Decoration only: the caller puts the
 * state into words beside the avatar.
 */
export function AgentAlive({
  life,
  motion,
  className,
  children,
}: {
  life: AgentLife;
  motion: boolean;
  className?: string;
  children: ReactNode;
}) {
  // A stamp only lands on a real transition from work to done. Tracked with
  // the render-time "previous value" pattern, so no effect re-renders.
  // It is marked fresh only when motion is on at that moment, and cleared
  // when the landing ends or motion drops, so a tab switch or a motion
  // toggle never replays it.
  const [seen, setSeen] = useState<AgentLifeState>(life.state);
  const [fresh, setFresh] = useState(false);
  if (seen !== life.state) {
    setSeen(life.state);
    setFresh(
      motion &&
        life.state === "done" &&
        (seen === "running" || seen === "thinking"),
    );
  } else if (fresh && !motion) {
    setFresh(false);
  }
  // Fallback clear for when the landing never runs (a treatment without the
  // paper motion layer, so no animationend): a stale fresh stamp must not
  // land later when paper comes back. 400ms outlasts the 280ms landing.
  useEffect(() => {
    if (!fresh) return;
    const timer = window.setTimeout(() => setFresh(false), 400);
    return () => window.clearTimeout(timer);
  }, [fresh]);
  const date = life.state === "done" ? stampDate(life.at) : null;

  return (
    <span
      className={cn(
        styles.alive,
        "paper-alive",
        life.state === "running" && "pinned",
        className,
      )}
      data-alive={life.state}
      data-live={motion ? "true" : undefined}
      data-stamp={fresh ? "fresh" : undefined}
      aria-hidden="true"
    >
      <span className={cn(styles.art, "paper-alive-art")}>{children}</span>
      {life.state === "failed" && <span className={styles.tear} />}
      {life.state === "done" && (
        <span
          className={cn(styles.stamp, "paper-alive-stamp")}
          onAnimationEnd={() => setFresh(false)}
        >
          {date ?? "Done"}
        </span>
      )}
    </span>
  );
}
