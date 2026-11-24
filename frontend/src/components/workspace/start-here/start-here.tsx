"use client";

import {
  ArrowRightIcon,
  CheckCircle2Icon,
  CircleIcon,
  CopyIcon,
  GraduationCapIcon,
  LayoutDashboardIcon,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { buildChatPromptHref } from "@/components/workspace/control-panel/control-panel-data";
import { FilterGroup, pageStyles } from "@/components/workspace/page-body";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useAgents } from "@/core/agents/hooks";
import { useAuth, useIsClient } from "@/core/auth/AuthProvider";
import { writeTextToClipboard } from "@/core/clipboard";
import { useMomentumInternalEnabled } from "@/core/features";
import { cn } from "@/lib/utils";

import {
  BUSINESS_OWNER_LESSONS,
  PROMPT_LIBRARY,
  PROMPT_LIBRARY_CATEGORIES,
  readStartHereProgress,
  writeStartHereProgress,
  type PromptLibraryCategory,
} from "./start-here-data";

import styles from "./start-here.module.css";

export function StartHereAcademyPage() {
  useEffect(() => {
    document.title = "Start Here / Academy | MomoBot";
  }, []);

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className={pageStyles.page}>
        <StartHereAcademyBody />
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

export function StartHereAcademyBody() {
  const { user } = useAuth();
  const isClient = useIsClient();
  const { agents } = useAgents();
  const { enabled: internalEnabled } = useMomentumInternalEnabled();
  const scopeKey = user?.id ?? "guest";

  const [completed, setCompleted] = useState<Record<string, boolean>>(() =>
    readStartHereProgress(scopeKey),
  );
  const [category, setCategory] = useState<PromptLibraryCategory>("All");
  const [copiedId, setCopiedId] = useState<string | null>(null);

  useEffect(() => {
    setCompleted(readStartHereProgress(scopeKey));
  }, [scopeKey]);

  const doneCount = BUSINESS_OWNER_LESSONS.filter(
    (lesson) => completed[lesson.id],
  ).length;
  const percent = Math.round((doneCount / BUSINESS_OWNER_LESSONS.length) * 100);

  const filteredPrompts = useMemo(() => {
    if (category === "All") {
      return PROMPT_LIBRARY;
    }
    return PROMPT_LIBRARY.filter((item) => item.category === category);
  }, [category]);

  const toggleLesson = (id: string) => {
    setCompleted((prev) => {
      const next = { ...prev, [id]: !prev[id] };
      writeStartHereProgress(scopeKey, next);
      return next;
    });
  };

  const handleCopy = async (id: string, text: string) => {
    const ok = await writeTextToClipboard(text);
    if (ok) {
      setCopiedId(id);
      setTimeout(() => {
        setCopiedId((current) => (current === id ? null : current));
      }, 2000);
    }
  };

  return (
    <main className={styles.frame} data-testid="start-here-academy">
      <header className={styles.headerRow}>
        <div>
          <p className={pageStyles.eyebrow}>Business Owner Track</p>
          <h1 className="mt-1">Start Here / Academy</h1>
          <p className={cn(pageStyles.lede, "mt-1")}>
            Five short guides and a library of ready-to-run prompts to help you
            build pages, local SEO content, weekly posts, and growth plans in
            minutes.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline" size="sm">
            <Link href="/workspace/control-panel">
              <LayoutDashboardIcon className="size-4" />
              Control Panel
            </Link>
          </Button>
          {internalEnabled && !isClient && (
            <Button asChild variant="secondary" size="sm">
              <Link href="/workspace/academy">
                <GraduationCapIcon className="size-4" />
                Staff AI Academy
              </Link>
            </Button>
          )}
        </div>
      </header>

      <section
        className={styles.progressCard}
        aria-label="Quick-start progress"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <strong className="text-sm">
            {doneCount} of {BUSINESS_OWNER_LESSONS.length} quick-start lessons
            done
          </strong>
          <span
            className={cn(pageStyles.figure, "text-muted-foreground text-xs")}
          >
            {percent}% complete
          </span>
        </div>
        <Progress
          value={percent}
          aria-label="Start Here lessons completed"
          aria-valuetext={`${doneCount} of ${BUSINESS_OWNER_LESSONS.length} lessons`}
        />
      </section>

      <section aria-labelledby="owner-track-heading" className="space-y-3">
        <div>
          <p className={pageStyles.eyebrow}>Step-by-Step</p>
          <h2 id="owner-track-heading" className="mt-0.5 text-xl">
            5-Lesson Quick Start
          </h2>
        </div>

        <div className="space-y-3">
          {BUSINESS_OWNER_LESSONS.map((lesson, index) => {
            const isDone = Boolean(completed[lesson.id]);
            const tryHref = buildChatPromptHref({
              isClient,
              agents,
              prompt: lesson.tryPrompt,
            });
            return (
              <details
                key={lesson.id}
                className={styles.lessonCard}
                open={index === 0}
              >
                <summary className={styles.lessonSummary}>
                  <div className="flex min-w-0 items-center gap-2.5">
                    {isDone ? (
                      <CheckCircle2Icon className="text-primary size-4 shrink-0" />
                    ) : (
                      <CircleIcon className="text-muted-foreground size-4 shrink-0" />
                    )}
                    <span className="text-sm font-semibold">
                      {index + 1}. {lesson.title}
                    </span>
                  </div>
                  <span className="text-muted-foreground shrink-0 text-xs">
                    {lesson.minutes} min
                  </span>
                </summary>
                <div className={styles.lessonBody}>
                  <p className="text-muted-foreground text-sm leading-relaxed">
                    {lesson.summary}
                  </p>
                  <ol className="list-decimal space-y-1.5 pl-5 text-sm">
                    {lesson.steps.map((step) => (
                      <li key={step}>{step}</li>
                    ))}
                  </ol>
                  <div className="bg-muted/50 rounded-md border p-3">
                    <p className="text-xs font-semibold">Try this in Chat</p>
                    <p className="text-muted-foreground mt-1 text-xs leading-relaxed">
                      {lesson.tryPrompt}
                    </p>
                    <div className="mt-2.5 flex flex-wrap items-center gap-2">
                      <Button asChild size="sm">
                        <Link href={tryHref}>
                          <span>Try in Chat</span>
                          <ArrowRightIcon className="size-3.5" />
                        </Link>
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          void handleCopy(lesson.id, lesson.tryPrompt)
                        }
                      >
                        <CopyIcon className="size-3.5" />
                        {copiedId === lesson.id ? "Copied" : "Copy prompt"}
                      </Button>
                      <label className="ml-auto inline-flex cursor-pointer items-center gap-2 text-xs font-medium">
                        <input
                          type="checkbox"
                          checked={isDone}
                          onChange={() => toggleLesson(lesson.id)}
                        />
                        Mark lesson done
                      </label>
                    </div>
                  </div>
                </div>
              </details>
            );
          })}
        </div>
      </section>

      <section aria-labelledby="prompt-library-heading" className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className={pageStyles.eyebrow}>Ready-to-Run Examples</p>
            <h2 id="prompt-library-heading" className="mt-0.5 text-xl">
              Example Prompt Library
            </h2>
          </div>
          <FilterGroup
            label="Prompt category"
            value={category}
            onChange={setCategory}
            options={PROMPT_LIBRARY_CATEGORIES.map((item) => ({
              value: item,
              label: item,
            }))}
          />
        </div>

        <div className={styles.promptGrid} data-testid="prompt-library-grid">
          {filteredPrompts.map((item) => {
            const href = buildChatPromptHref({
              isClient,
              agents,
              prompt: item.prompt,
            });
            return (
              <article key={item.id} className={styles.promptCard}>
                <div className="space-y-1.5">
                  <span className={pageStyles.chip}>{item.category}</span>
                  <h3 className="text-sm font-bold">{item.title}</h3>
                  <p className="text-muted-foreground text-xs leading-relaxed">
                    {item.description}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2 pt-1">
                  <Button asChild size="sm" variant="outline">
                    <Link href={href}>
                      <span>Open in Chat</span>
                      <ArrowRightIcon className="size-3.5" />
                    </Link>
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => void handleCopy(item.id, item.prompt)}
                  >
                    <CopyIcon className="size-3.5" />
                    {copiedId === item.id ? "Copied" : "Copy"}
                  </Button>
                </div>
              </article>
            );
          })}
        </div>
      </section>
    </main>
  );
}
