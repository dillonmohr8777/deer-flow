"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";

import {
  EmptyState,
  ErrorState,
  WorkingState,
} from "@/components/workspace/page-body";
import type { ConsoleRunItem } from "@/core/console";
import { formatCompactStamp } from "@/core/utils/datetime";
import { cn } from "@/lib/utils";

import styles from "./dispatch-board.module.css";

/*
 * Mission Control as a paper dispatch board (momo-week d9, slice 1).
 *
 * One slip per recorded run, filed into a lane by the run's REAL status:
 *   On the desk  pending / running   brass pin, because pins mean working
 *   Stamped      success             a dated ink stamp, no pin
 *   Returned     error / timeout     a torn corner folded back, the reason
 *                interrupted         the reason only: a stop is not a failure
 * Any other status lands in "Unsorted" with its raw word, never in a lane
 * that would claim more than the backend said. There is no brief or review
 * lane yet: nothing records those stages, so the board does not invent them.
 * Static state only; no motion is added (DESIGN.md's motion list is closed).
 *
 * Slice 2: stamped slips carry the stamp beside the words, not under them,
 * so a long run of finished work stays short; the tear folds back to show
 * the kraft underside (the same language as the Command Center's failed
 * agent); an interrupted run and a queued one read in neutral ink.
 */

export type DispatchLane = "desk" | "stamped" | "returned" | "unsorted";

const LANE_OF: Record<string, DispatchLane> = {
  pending: "desk",
  running: "desk",
  success: "stamped",
  error: "returned",
  timeout: "returned",
  interrupted: "returned",
};

export function laneOf(status: string): DispatchLane {
  return LANE_OF[status] ?? "unsorted";
}

const LANES: {
  id: DispatchLane;
  title: string;
  empty: string;
}[] = [
  {
    id: "desk",
    title: "On the desk",
    empty: "Nothing is being worked on right now.",
  },
  {
    id: "stamped",
    title: "Stamped",
    empty: "Finished work lands here with its date.",
  },
  {
    id: "returned",
    title: "Returned",
    empty: "No failed or stopped runs in this batch.",
  },
  {
    id: "unsorted",
    title: "Unsorted",
    empty: "",
  },
];

const RETURN_WORD: Record<string, string> = {
  error: "Failed",
  timeout: "Timed out",
  interrupted: "Interrupted",
};

/** "Sep 24" in the viewer's zone; null when the time was not recorded. */
export function stampDate(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
  }).format(date);
}

/** d2's compact stamp in a real <time>; omitted, not invented, when unrecorded. */
function Started({ value }: { value: string | null }) {
  const stamp = formatCompactStamp(value, "en-US");
  if (!value || !stamp) return <span>Start time not recorded</span>;
  return (
    <span>
      Started <time dateTime={value}>{stamp}</time>
    </span>
  );
}

/** Real failures only. An interrupted run was stopped, not broken. */
export function isFailure(status: string): boolean {
  return status === "error" || status === "timeout";
}

export function groupRuns(runs: ConsoleRunItem[]) {
  const groups: Record<DispatchLane, ConsoleRunItem[]> = {
    desk: [],
    stamped: [],
    returned: [],
    unsorted: [],
  };
  for (const run of runs) groups[laneOf(run.status)].push(run);
  return groups;
}

type Props = {
  runs: ConsoleRunItem[] | undefined;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onOpen: (run: ConsoleRunItem) => void;
  selectedRunId: string | null;
  agentLabel: (assistantId: string | null) => string;
  startPath: string;
  onShowAll: () => void;
  hasMore: boolean;
  /** Command Center's own panel and heading classes, so every treatment's
      overrides apply to the board exactly as they do to its neighbours. */
  panelClassName?: string;
  headClassName?: string;
};

export function DispatchBoard({
  runs,
  loading,
  error,
  onRetry,
  onOpen,
  selectedRunId,
  agentLabel,
  startPath,
  onShowAll,
  hasMore,
  panelClassName,
  headClassName,
}: Props) {
  return (
    <section
      className={`${styles.board} ${panelClassName ?? ""}`}
      aria-labelledby="dispatch-heading"
    >
      <div className={`${styles.head} ${headClassName ?? ""}`}>
        <div>
          <h2 id="dispatch-heading">Dispatch board</h2>
          <p>
            Every recorded run as a slip, filed by what actually happened to it.
          </p>
        </div>
        <button type="button" className={styles.showAll} onClick={onShowAll}>
          All runs in Jobs <ArrowRight size={15} aria-hidden="true" />
        </button>
      </div>
      {error ? (
        <ErrorState
          message="The dispatch board could not load your runs."
          detail={error}
          action={
            <button type="button" onClick={onRetry}>
              Try again
            </button>
          }
        />
      ) : loading || !runs ? (
        <WorkingState label="Loading the dispatch board" />
      ) : runs.length === 0 ? (
        <EmptyState
          momo="lead"
          title="No missions yet"
          action={
            <Link className={styles.showAll} href={startPath}>
              Start a mission <ArrowRight size={15} aria-hidden="true" />
            </Link>
          }
        >
          Each mission you start gets a slip here, from the desk to its stamped
          receipt.
        </EmptyState>
      ) : (
        <Lanes
          runs={runs}
          onOpen={onOpen}
          selectedRunId={selectedRunId}
          agentLabel={agentLabel}
          hasMore={hasMore}
        />
      )}
    </section>
  );
}

function Lanes({
  runs,
  onOpen,
  selectedRunId,
  agentLabel,
  hasMore,
}: Pick<Props, "onOpen" | "selectedRunId" | "agentLabel" | "hasMore"> & {
  runs: ConsoleRunItem[];
}) {
  const groups = groupRuns(runs);
  return (
    <>
      <div className={styles.lanes}>
        {LANES.filter(
          (lane) => lane.id !== "unsorted" || groups.unsorted.length > 0,
        ).map((lane) => (
          <section
            key={lane.id}
            className={styles.lane}
            data-lane={lane.id}
            data-failed={
              lane.id === "returned" &&
              groups.returned.some((run) => isFailure(run.status))
                ? "true"
                : undefined
            }
            aria-labelledby={`lane-${lane.id}`}
          >
            <h3 className={styles.laneTitle} id={`lane-${lane.id}`}>
              {lane.title}
              <span className={styles.count}>{groups[lane.id].length}</span>
            </h3>
            {groups[lane.id].length === 0 ? (
              <p className={styles.laneEmpty}>{lane.empty}</p>
            ) : (
              <ol className={styles.slips}>
                {groups[lane.id].map((run, index) => (
                  <li key={run.run_id}>
                    <Slip
                      run={run}
                      lane={lane.id}
                      tilt={index % 3}
                      selected={selectedRunId === run.run_id}
                      agent={agentLabel(run.assistant_id)}
                      onOpen={onOpen}
                    />
                  </li>
                ))}
              </ol>
            )}
          </section>
        ))}
      </div>
      <p className={styles.batch}>
        {hasMore
          ? `Showing the latest ${runs.length} runs. Older work is in Jobs.`
          : `Showing all ${runs.length} recorded runs.`}
      </p>
    </>
  );
}

function Slip({
  run,
  lane,
  tilt,
  selected,
  agent,
  onOpen,
}: {
  run: ConsoleRunItem;
  lane: DispatchLane;
  tilt: number;
  selected: boolean;
  agent: string;
  onOpen: (run: ConsoleRunItem) => void;
}) {
  const working = run.status === "running";
  const failed = isFailure(run.status);
  const date = stampDate(run.updated_at);
  const title = run.thread_title ?? "Untitled assignment";
  return (
    <button
      type="button"
      // "pinned" is paper.css's own unscoped hook: a brass pin, which means
      // working. Only a running slip gets it; a queued one waits unpinned.
      className={cn(styles.slip, working && "pinned")}
      data-lane={lane}
      data-status={run.status}
      data-failed={failed ? "true" : undefined}
      data-tilt={tilt}
      aria-pressed={selected}
      // Titles clamp to two lines; the native tooltip keeps the whole one.
      title={title}
      onClick={() => onOpen(run)}
    >
      <span className={styles.slipTitle}>{title}</span>
      <span className={styles.slipMeta}>
        <span>{agent}</span>
        <span aria-hidden="true">·</span>
        <Started value={run.created_at} />
      </span>
      {lane === "desk" ? (
        <span
          className={styles.word}
          data-tone={working ? "active" : "unknown"}
        >
          {working ? "Working" : "Queued"}
        </span>
      ) : null}
      {lane === "stamped" ? (
        <span className={styles.stamp} data-testid="ink-stamp">
          <span>Done</span>
          <span>{date ?? "Date not recorded"}</span>
        </span>
      ) : null}
      {lane === "returned" ? (
        <span className={styles.word} data-tone={failed ? "danger" : "unknown"}>
          {RETURN_WORD[run.status] ?? run.status}
        </span>
      ) : null}
      {failed ? (
        // The torn piece, folded down: decoration, the word says it.
        <span className={styles.tear} data-part="tear" aria-hidden="true" />
      ) : null}
      {lane === "unsorted" ? (
        <span className={styles.word} data-tone="unknown">
          {run.status || "Status not recorded"}
        </span>
      ) : null}
    </button>
  );
}
