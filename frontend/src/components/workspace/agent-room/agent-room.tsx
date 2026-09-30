"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  EmptyState,
  ErrorState,
  pageStyles,
  StatusTag,
  WorkingState,
} from "@/components/workspace/page-body";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import {
  AGENT_ROOM_ROLES,
  useAgentRoomAccess,
  useAgentRoomMessages,
  usePostAgentRoomMessage,
  type AgentRoomMessage,
  type AgentRoomMessageType,
} from "@/core/agent-room";
import { cn } from "@/lib/utils";

function messageTone(type: AgentRoomMessageType) {
  if (type === "finding" || type === "deliverable") return "ok" as const;
  if (type === "question" || type === "handoff") return "attention" as const;
  return "unknown" as const;
}

function messageLabel(type: AgentRoomMessageType) {
  return type.charAt(0).toUpperCase() + type.slice(1);
}

function formatMessageTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      });
}

function MessageRow({ message }: { message: AgentRoomMessage }) {
  const label =
    message.author_kind === "owner"
      ? "You"
      : message.agent_role.trim().length > 0
        ? message.agent_role
        : message.agent_id?.trim().length
          ? message.agent_id
          : "MomoBot Agent";
  return (
    <article className="border-b py-4 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        <strong className="text-sm font-semibold">{label}</strong>
        <StatusTag tone={messageTone(message.message_type)}>
          {messageLabel(message.message_type)}
        </StatusTag>
        <time
          className="text-muted-foreground ml-auto text-xs"
          dateTime={message.created_at}
        >
          {formatMessageTime(message.created_at)}
        </time>
      </div>
      <p className="mt-2 text-sm leading-6 break-words whitespace-pre-wrap">
        {message.body}
      </p>
    </article>
  );
}

export function AgentRoom() {
  const { ownerId, enabled, isLoading, canWrite } = useAgentRoomAccess();
  const router = useRouter();
  const [storedDraft, setDraft] = useState({ ownerId, body: "" });
  const draft = storedDraft.ownerId === ownerId ? storedDraft.body : "";
  const messages = useAgentRoomMessages();
  const postMessage = usePostAgentRoomMessage();

  useEffect(() => {
    if (!isLoading && !enabled) router.replace("/workspace/command-center");
  }, [enabled, isLoading, router]);

  useEffect(() => {
    if (enabled) document.title = "Agent Room | MomoBot";
  }, [enabled]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body = draft.trim();
    if (!body || !canWrite || postMessage.isPending) return;
    try {
      await postMessage.mutateAsync({ body, message_type: "instruction" });
      setDraft((previous) =>
        previous.ownerId === ownerId && previous.body === draft
          ? { ownerId, body: "" }
          : previous,
      );
    } catch {
      // The mutation error stays visible below the composer.
    }
  }

  if (!enabled) return <WorkingState label="Loading" className="m-8" />;

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className={cn(pageStyles.page, "overflow-hidden")}>
        <ScrollArea className="size-full">
          <main className="mx-auto w-full max-w-7xl px-5 py-8 md:px-8">
            <p className={pageStyles.eyebrow}>Dillon’s private workspace</p>
            <h1 className="mt-1 text-3xl font-semibold tracking-tight">
              Agent Room
            </h1>
            <p className={cn(pageStyles.lede, "mt-2 max-w-3xl")}>
              Shared progress, findings, and handoffs from the Momentum agents.
              Send work through MomoBot chat; agents read this room and post
              back here.
            </p>

            <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(220px,0.32fr)_minmax(0,1fr)]">
              <aside
                aria-labelledby="agent-room-roster"
                className="border-t pt-4"
              >
                <h2 id="agent-room-roster" className="text-base font-semibold">
                  The team
                </h2>
                <ul className="mt-3 divide-y">
                  {AGENT_ROOM_ROLES.map((role) => (
                    <li key={role.id} className="py-3">
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <h3 className="text-sm font-medium">{role.name}</h3>
                        <span className="text-muted-foreground text-xs">
                          {role.model}
                        </span>
                      </div>
                      <p className="text-muted-foreground mt-1 text-sm leading-5">
                        {role.focus}
                      </p>
                    </li>
                  ))}
                </ul>
                <p className="text-muted-foreground mt-4 border-l-2 pl-3 text-sm leading-5">
                  Website work remains a reviewable draft. Agents do not email
                  Momentum clients or post to Slack.
                </p>
              </aside>

              <section
                aria-labelledby="agent-room-feed"
                className="min-w-0 border-t pt-4"
              >
                <div className="flex items-baseline justify-between gap-3">
                  <h2 id="agent-room-feed" className="text-base font-semibold">
                    Room activity
                  </h2>
                  <span className="text-muted-foreground text-xs">
                    Refreshes every 10 seconds
                  </span>
                </div>
                {messages.isError ? (
                  <ErrorState
                    className="mt-5"
                    message="Couldn't load the Agent Room."
                    detail={messages.error.message}
                    action={
                      <Button
                        variant="outline"
                        size="sm"
                        className="min-h-11"
                        onClick={() => void messages.refetch()}
                      >
                        Try again
                      </Button>
                    }
                  />
                ) : messages.isLoading ? (
                  <WorkingState
                    label="Loading room activity"
                    className="mt-5"
                  />
                ) : messages.data?.length ? (
                  <div className="mt-2 divide-y">
                    {messages.data.map((message) => (
                      <MessageRow key={message.id} message={message} />
                    ))}
                  </div>
                ) : (
                  <EmptyState
                    className="mt-5"
                    momo="lead"
                    title="The room is ready"
                  >
                    Start a MomoBot chat and assign a bounded Momentum task.
                    Agents will post progress, evidence, and handoffs here.
                  </EmptyState>
                )}

                <form onSubmit={submit} className="mt-6 border-t pt-4">
                  <label
                    htmlFor="agent-room-instruction"
                    className="text-sm font-medium"
                  >
                    Leave an instruction or note
                  </label>
                  <textarea
                    id="agent-room-instruction"
                    value={draft}
                    onChange={(event) =>
                      setDraft({ ownerId, body: event.target.value })
                    }
                    disabled={!canWrite}
                    maxLength={4000}
                    rows={3}
                    className="bg-background focus-visible:ring-ring mt-2 block w-full resize-y rounded-md border px-3 py-2 text-sm outline-none focus-visible:ring-2"
                    placeholder="Agents will read this at the start of their next run."
                  />
                  <div className="mt-2 flex items-center justify-between gap-3">
                    <span className="text-muted-foreground text-xs">
                      {draft.length}/4000
                    </span>
                    <Button
                      type="submit"
                      className="min-h-11"
                      disabled={
                        !canWrite || !draft.trim() || postMessage.isPending
                      }
                    >
                      {postMessage.isPending ? "Posting…" : "Post to room"}
                    </Button>
                  </div>
                  {postMessage.isError ? (
                    <p className="text-destructive mt-2 text-sm" role="alert">
                      {postMessage.error.message}
                    </p>
                  ) : null}
                </form>
              </section>
            </div>
          </main>
        </ScrollArea>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
