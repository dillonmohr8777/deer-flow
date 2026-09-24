"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { useTodayBrief } from "@/core/briefs";
import type {
  BriefActivityItem,
  BriefDueTask,
  BriefWaitingItem,
  TodayBrief,
} from "@/core/briefs";
import type { Translations } from "@/core/i18n/locales";
import {
  buildComposerDraftKey,
  getSessionComposerDraftStorage,
  writeComposerDraft,
} from "@/core/threads/composer-draft";
import { pathOfThread } from "@/core/threads/utils";

import styles from "./daily.module.css";

type Copy = Translations["dailyBrief"];

function kindLabel(kind: BriefActivityItem["kind"], copy: Copy): string {
  switch (kind) {
    case "thread":
      return copy.kindThread;
    case "run_success":
      return copy.kindRunSuccess;
    case "run_failed":
      return copy.kindRunFailed;
    case "document":
      return copy.kindDocument;
    case "scheduled_task_success":
      return copy.kindScheduledSuccess;
    case "scheduled_task_failed":
      return copy.kindScheduledFailed;
  }
}

function itemHref(item: {
  thread_id: string | null;
  agent_name?: string | null;
}): string | null {
  if (!item.thread_id) return null;
  return pathOfThread(item.thread_id, {
    agent_name: item.agent_name ?? undefined,
  });
}

function ActivityRow({ item, copy }: { item: BriefActivityItem; copy: Copy }) {
  const href = itemHref(item);
  const title = item.title ?? copy.untitledChat;
  const isFailure =
    item.kind === "run_failed" || item.kind === "scheduled_task_failed";
  return (
    <li
      className={styles.briefRow}
      data-brief-alert={isFailure ? "true" : undefined}
    >
      <p className={styles.briefKind}>{kindLabel(item.kind, copy)}</p>
      <p className={styles.briefTitle}>
        {href ? <Link href={href}>{title}</Link> : title}
      </p>
      {item.detail ? <p className={styles.briefDetail}>{item.detail}</p> : null}
      {item.client_name ? (
        <p className={styles.briefMeta}>{item.client_name}</p>
      ) : null}
    </li>
  );
}

function DueRow({ item }: { item: BriefDueTask }) {
  const href = itemHref(item);
  const time = new Date(item.next_run_at).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
  return (
    <li className={styles.briefRow}>
      <p className={styles.briefTitle}>
        {href ? <Link href={href}>{item.title}</Link> : item.title}
      </p>
      <p className={styles.briefMeta}>{time}</p>
    </li>
  );
}

function WaitingRow({ item, copy }: { item: BriefWaitingItem; copy: Copy }) {
  const href = itemHref(item);
  const title = item.title ?? copy.untitledChat;
  const label =
    item.kind === "interrupted"
      ? copy.waitingInterrupted
      : copy.waitingClarification;
  return (
    <li className={styles.briefRow} data-brief-alert="true">
      <p className={styles.briefKind}>{label}</p>
      <p className={styles.briefTitle}>
        {href ? <Link href={href}>{title}</Link> : title}
      </p>
      {item.client_name ? (
        <p className={styles.briefMeta}>{item.client_name}</p>
      ) : null}
    </li>
  );
}

function describeActivity(item: BriefActivityItem, copy: Copy): string {
  const bits = [kindLabel(item.kind, copy), item.title ?? copy.untitledChat];
  if (item.client_name) bits.push(item.client_name);
  const text = `- ${bits.join(": ")}`;
  return item.detail ? `${text} (${item.detail})` : text;
}

function describeDue(item: BriefDueTask): string {
  return `- ${item.title}`;
}

function describeWaiting(item: BriefWaitingItem, copy: Copy): string {
  const label =
    item.kind === "interrupted"
      ? copy.waitingInterrupted
      : copy.waitingClarification;
  const title = item.title ?? copy.untitledChat;
  return item.client_name
    ? `- ${title} (${item.client_name}): ${label}`
    : `- ${title}: ${label}`;
}

function buildWriteItUpPrompt(brief: TodayBrief, copy: Copy): string {
  const sections: string[] = [copy.writeItUpIntro];
  if (brief.assigned_clients.length) {
    sections.push(
      [
        copy.writeItUpClients,
        ...brief.assigned_clients.map((c) => `- ${c.display_name}`),
      ].join("\n"),
    );
  }
  if (brief.activity.length) {
    sections.push(
      [
        copy.writeItUpActivity,
        ...brief.activity.map((item) => describeActivity(item, copy)),
      ].join("\n"),
    );
  }
  if (brief.due_today.length) {
    sections.push(
      [copy.writeItUpDue, ...brief.due_today.map(describeDue)].join("\n"),
    );
  }
  if (brief.waiting_on_you.length) {
    sections.push(
      [
        copy.writeItUpWaiting,
        ...brief.waiting_on_you.map((item) => describeWaiting(item, copy)),
      ].join("\n"),
    );
  }
  if (sections.length === 1) {
    sections.push(copy.writeItUpNothing);
  }
  return sections.join("\n\n");
}

export function YourMorning({
  signedIn,
  userId,
  copy,
}: {
  signedIn: boolean;
  userId: string | null;
  copy: Copy;
}) {
  const router = useRouter();
  const state = useTodayBrief(signedIn);

  if (!signedIn) {
    return null;
  }

  const handleWriteItUp = (brief: TodayBrief) => {
    if (!userId) return;
    const storage = getSessionComposerDraftStorage();
    const key = buildComposerDraftKey({
      userId,
      agentName: null,
      threadId: "new",
    });
    writeComposerDraft(storage, key, {
      text: buildWriteItUpPrompt(brief, copy),
      skillName: null,
    });
    router.push("/workspace/chats/new");
  };

  const isEmpty =
    state.status === "ready" &&
    state.brief.activity.length === 0 &&
    state.brief.due_today.length === 0 &&
    state.brief.waiting_on_you.length === 0;

  return (
    // No parallax/tilt/transition lives in this section, so there is
    // nothing to gate behind useDailyMotion(): it satisfies "respect
    // reduced motion" by never introducing motion in the first place.
    <section className={styles.brief} aria-labelledby="daily-brief-heading">
      <div className={styles.briefHeader}>
        <h2 id="daily-brief-heading" className={styles.sectionHeading}>
          {copy.title}
        </h2>
        {state.status === "ready" ? (
          <button
            type="button"
            className={styles.briefWriteUp}
            onClick={() => handleWriteItUp(state.brief)}
          >
            {copy.writeItUp}
          </button>
        ) : null}
      </div>

      {state.status === "loading" ? (
        <p className={styles.quiet}>{copy.loading}</p>
      ) : null}
      {state.status === "error" ? (
        <p className={styles.quiet}>{copy.error}</p>
      ) : null}

      {state.status === "ready" ? (
        <>
          {state.brief.assigned_clients.length > 0 ? (
            <p className={styles.briefClients}>
              <span className={styles.briefClientsLabel}>
                {copy.clientsLabel}
              </span>{" "}
              {state.brief.assigned_clients
                .map((c) => c.display_name)
                .join(", ")}
            </p>
          ) : null}

          {isEmpty ? (
            <p className={styles.quiet}>
              {copy.emptyTitle} {copy.emptyBody}
            </p>
          ) : (
            <div className={styles.briefColumns}>
              {state.brief.waiting_on_you.length > 0 ? (
                <div>
                  <h3 className={styles.briefSubheading}>
                    {copy.waitingHeading}
                  </h3>
                  <ul className={styles.briefList}>
                    {state.brief.waiting_on_you.map((item) => (
                      <WaitingRow
                        key={`${item.thread_id}:${item.run_id}`}
                        item={item}
                        copy={copy}
                      />
                    ))}
                  </ul>
                </div>
              ) : null}

              {state.brief.due_today.length > 0 ? (
                <div>
                  <h3 className={styles.briefSubheading}>{copy.dueHeading}</h3>
                  <ul className={styles.briefList}>
                    {state.brief.due_today.map((item) => (
                      <DueRow key={item.task_id} item={item} />
                    ))}
                  </ul>
                </div>
              ) : null}

              {state.brief.activity.length > 0 ? (
                <div>
                  <h3 className={styles.briefSubheading}>
                    {copy.activityHeading}
                  </h3>
                  <ul className={styles.briefList}>
                    {state.brief.activity.map((item, index) => (
                      <ActivityRow
                        key={`${item.kind}:${item.thread_id ?? index}`}
                        item={item}
                        copy={copy}
                      />
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}
