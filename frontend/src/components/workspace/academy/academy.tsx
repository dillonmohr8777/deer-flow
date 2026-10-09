"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  ErrorState,
  pageStyles,
  WorkingState,
} from "@/components/workspace/page-body";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import {
  nextLessonId,
  trackProgress,
  useAcademy,
  useSetLessonCompleted,
  type AcademyLesson,
  type AcademyTrack,
} from "@/core/academy";
import { writeTextToClipboard } from "@/core/clipboard";
import { useMomentumInternalEnabled } from "@/core/features";
import { cn } from "@/lib/utils";

import styles from "./academy.module.css";

/**
 * AI Academy: Momentum staff training. Same gate as Team
 * (features.momentum_internal); the curriculum itself is served by
 * /api/academy behind the same rule, so a client never receives it.
 */
export function AcademyPage() {
  const { enabled, isLoading } = useMomentumInternalEnabled();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !enabled) router.replace("/workspace/command-center");
  }, [enabled, isLoading, router]);

  useEffect(() => {
    if (enabled) document.title = "AI Academy | MomoBot";
  }, [enabled]);

  if (!enabled) {
    return <WorkingState label="Loading" className="m-8" />;
  }
  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className={pageStyles.page}>
        <AcademyBody />
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

function AcademyBody() {
  const academy = useAcademy();
  const [openId, setOpenId] = useState<string | null>(null);

  if (academy.isError) {
    return (
      <div className={styles.frame}>
        <ErrorState
          message="Couldn't load the Academy."
          detail={academy.error.message}
          action={
            <Button
              variant="outline"
              size="sm"
              onClick={() => void academy.refetch()}
            >
              Try again
            </Button>
          }
        />
      </div>
    );
  }
  if (academy.isLoading || !academy.data) {
    return <WorkingState label="Loading the Academy" className="m-8" />;
  }

  const data = academy.data;
  const next = nextLessonId(data);
  const percent =
    data.lesson_count > 0
      ? Math.round((data.completed_count / data.lesson_count) * 100)
      : 0;

  return (
    <div className={styles.frame} data-testid="academy">
      <header>
        <p className={pageStyles.eyebrow}>Momentum only</p>
        <h1 className="mt-1">AI Academy</h1>
        <p className={cn(pageStyles.lede, "mt-1")}>
          Short lessons on MomoBot and the AI tools we use for clients. Each one
          ends with something to try. Clients never see this page.
        </p>
      </header>

      <section className={styles.progressCard} aria-label="Your progress">
        <div className={styles.progressRow}>
          <strong>
            {data.completed_count} of {data.lesson_count} lessons done
          </strong>
          {next ? (
            <Button
              variant="outline"
              onClick={() => {
                setOpenId(next);
                document
                  .getElementById(`lesson-${next}`)
                  ?.scrollIntoView({ block: "start" });
              }}
            >
              {data.completed_count === 0 ? "Start" : "Continue"}
            </Button>
          ) : (
            <span className={styles.count}>All done. Nice work.</span>
          )}
        </div>
        <Progress
          value={percent}
          aria-label="Lessons completed"
          aria-valuetext={`${data.completed_count} of ${data.lesson_count} lessons`}
        />
      </section>

      {data.tracks.map((track) => (
        <Track
          key={track.id}
          track={track}
          openId={openId}
          onToggle={(id, open) => setOpenId(open ? id : null)}
        />
      ))}
    </div>
  );
}

function Track({
  track,
  openId,
  onToggle,
}: {
  track: AcademyTrack;
  openId: string | null;
  onToggle: (id: string, open: boolean) => void;
}) {
  const { done, total } = trackProgress(track);
  const headingId = `track-${track.id}`;
  return (
    <section className={styles.track} aria-labelledby={headingId}>
      <div className={styles.trackHead}>
        <h2 id={headingId}>{track.title}</h2>
        <span className={styles.count}>
          {done}/{total} done
        </span>
      </div>
      <p className={pageStyles.lede}>{track.summary}</p>
      <ol className={styles.lessons}>
        {track.lessons.map((lesson) => (
          <li key={lesson.id}>
            <Lesson
              lesson={lesson}
              open={openId === lesson.id}
              onToggle={(open) => onToggle(lesson.id, open)}
            />
          </li>
        ))}
      </ol>
    </section>
  );
}

function Lesson({
  lesson,
  open,
  onToggle,
}: {
  lesson: AcademyLesson;
  open: boolean;
  onToggle: (open: boolean) => void;
}) {
  const setCompleted = useSetLessonCompleted();
  const [copied, setCopied] = useState(false);
  // Pending value while a save is in flight, so the box ticks on the click
  // itself instead of after the round trip; the server value wins after.
  const [pending, setPending] = useState<boolean | null>(null);
  const checked = pending ?? lesson.completed;

  return (
    <details
      id={`lesson-${lesson.id}`}
      className={styles.lesson}
      data-done={checked}
      open={open}
      onToggle={(event) => {
        const nowOpen = (event.currentTarget as HTMLDetailsElement).open;
        if (nowOpen !== open) onToggle(nowOpen);
      }}
    >
      <summary className={styles.lessonSummary}>
        <span className={styles.doneMark} aria-hidden>
          {lesson.completed ? "✓" : ""}
        </span>
        <span className={styles.lessonTitle}>{lesson.title}</span>
        <span className={styles.minutes}>{lesson.minutes} min</span>
        <span className="sr-only">
          {lesson.completed ? ", done" : ", not done"}
        </span>
      </summary>
      <div className={styles.lessonBody}>
        <p>{lesson.summary}</p>
        {lesson.video_slot ? (
          lesson.video_url ? (
            <video
              className={styles.video}
              src={lesson.video_url}
              controls
              preload="metadata"
            >
              <track kind="captions" />
            </video>
          ) : (
            <p className={styles.videoPending}>
              Momo explainer video for this lesson is in production.
            </p>
          )
        ) : null}
        <ol className={styles.steps}>
          {lesson.steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
        <div className={styles.tryIt}>
          <strong>Try it in MomoBot</strong>
          <p>{lesson.try_it}</p>
          <div className={styles.actions}>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                void writeTextToClipboard(lesson.try_it).then((ok) =>
                  setCopied(ok),
                )
              }
            >
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
        </div>
        <label className={styles.checkbox}>
          <input
            type="checkbox"
            checked={checked}
            onChange={(event) => {
              const next = event.target.checked;
              setPending(next);
              setCompleted.mutate(
                { lessonId: lesson.id, completed: next },
                { onSettled: () => setPending(null) },
              );
            }}
          />
          Mark this lesson done
        </label>
        {setCompleted.isError ? (
          <p className={styles.errorText} role="alert">
            {setCompleted.error.message}
          </p>
        ) : null}
      </div>
    </details>
  );
}
