"use client";

import { useRouter } from "next/navigation";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import {
  EmptyState,
  ErrorState,
  pageStyles,
  WorkingState,
} from "@/components/workspace/page-body";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useAuth } from "@/core/auth/AuthProvider";
import { useMomentumInternalEnabled } from "@/core/features";
import {
  useCreateTeamChannel,
  usePostTeamMessage,
  useTeamChannels,
  useTeamMembers,
  useTeamMessages,
  type TeamChannel,
  type TeamMember,
} from "@/core/team";
import { cn } from "@/lib/utils";

import {
  authorLabel,
  canManageChannels,
  formatStamp,
  roleOf,
  startsGroup,
} from "./team-data";

import styles from "./team-board.module.css";

/**
 * Team: Momentum staff channels, a small in-product Slack. Renders only when
 * features.momentum_internal.enabled (the private instance plus a staff
 * role); the /api/team routes enforce the same rule and 404 everyone else.
 */
export function TeamBoard() {
  const { enabled, isLoading } = useMomentumInternalEnabled();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !enabled) router.replace("/workspace/command-center");
  }, [enabled, isLoading, router]);

  useEffect(() => {
    if (enabled) document.title = "Team | MomoBot";
  }, [enabled]);

  if (!enabled) {
    return <WorkingState label="Loading" className="m-8" />;
  }
  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className={pageStyles.page}>
        <TeamBody />
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

function TeamBody() {
  const { user } = useAuth();
  const channels = useTeamChannels();
  const members = useTeamMembers();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const list = useMemo(() => channels.data ?? [], [channels.data]);
  const selected = list.find((c) => c.id === selectedId) ?? list[0] ?? null;
  const myRole = roleOf(user?.id, members.data);

  return (
    <div className={styles.frame} data-testid="team-board">
      <header>
        <p className={pageStyles.eyebrow}>Momentum only</p>
        <h1 className="mt-1">Team</h1>
        <p className={cn(pageStyles.lede, "mt-1")}>
          Channels for the Momentum team. Clients never see this page.
        </p>
      </header>
      <div className={styles.layout}>
        <nav className={styles.channels} aria-label="Channels">
          {channels.isError ? (
            <ErrorState
              message="Couldn't load channels."
              detail={channels.error.message}
              action={
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void channels.refetch()}
                >
                  Try again
                </Button>
              }
            />
          ) : channels.isLoading ? (
            <WorkingState label="Loading channels" />
          ) : (
            <ul className={styles.channelList}>
              {list.map((channel) => (
                <li key={channel.id}>
                  <button
                    type="button"
                    className={styles.channelButton}
                    aria-current={channel.id === selected?.id}
                    onClick={() => setSelectedId(channel.id)}
                  >
                    <span className={styles.hash} aria-hidden>
                      #
                    </span>
                    {channel.slug}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {canManageChannels(myRole) ? (
            <AddChannel onCreated={(channel) => setSelectedId(channel.id)} />
          ) : null}
        </nav>
        <section className={styles.conversation} aria-label="Conversation">
          {selected ? (
            // Keyed by channel so a half-typed message never follows you
            // into another channel (the Board's f5 bug, avoided up front).
            <Channel
              key={selected.id}
              channel={selected}
              members={members.data}
              currentUserId={user?.id ?? null}
            />
          ) : channels.isLoading ? null : (
            <EmptyState momo="lead" title="No channels yet">
              Channels appear here once the workspace is set up.
            </EmptyState>
          )}
        </section>
      </div>
    </div>
  );
}

function Channel({
  channel,
  members,
  currentUserId,
}: {
  channel: TeamChannel;
  members: TeamMember[] | undefined;
  currentUserId: string | null;
}) {
  const messages = useTeamMessages(channel.id);
  const post = usePostTeamMessage();
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLLIElement>(null);
  const count = messages.data?.length ?? 0;

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [count]);

  const send = () => {
    const body = draft.trim();
    if (!body || post.isPending) return;
    post.mutate(
      { channelId: channel.id, body },
      { onSuccess: () => setDraft("") },
    );
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      send();
    }
  };

  const list = messages.data ?? [];
  return (
    <>
      <header className={styles.channelHead}>
        <h2>#{channel.slug}</h2>
        {channel.topic ? <p className={styles.hint}>{channel.topic}</p> : null}
      </header>
      {messages.isError ? (
        <ErrorState
          message="Couldn't load messages."
          detail={messages.error.message}
          action={
            <Button
              variant="outline"
              size="sm"
              onClick={() => void messages.refetch()}
            >
              Try again
            </Button>
          }
        />
      ) : messages.isLoading ? (
        <WorkingState label="Loading messages" />
      ) : (
        <ScrollArea className={styles.messages}>
          <ol className={styles.messageList} aria-live="polite">
            {list.length === 0 ? (
              <li className={styles.hint}>
                Nothing here yet. Say hello to the team.
              </li>
            ) : null}
            {list.map((message, index) => {
              const first = startsGroup(message, list[index - 1]);
              return (
                <li
                  key={message.id}
                  className={cn(styles.message, first && styles.groupStart)}
                >
                  {first ? (
                    <span className={styles.author}>
                      <span>
                        {authorLabel(
                          message.author_user_id,
                          members,
                          currentUserId,
                        )}
                      </span>
                      <time
                        className={styles.stamp}
                        dateTime={message.created_at}
                      >
                        {formatStamp(message.created_at)}
                      </time>
                    </span>
                  ) : null}
                  {message.body}
                </li>
              );
            })}
            <li ref={endRef} aria-hidden />
          </ol>
        </ScrollArea>
      )}
      <form
        className={styles.composer}
        onSubmit={(event) => {
          event.preventDefault();
          send();
        }}
      >
        <label htmlFor="team-composer" className="sr-only">
          Message #{channel.slug}
        </label>
        <Textarea
          id="team-composer"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={`Message #${channel.slug}`}
          rows={2}
          maxLength={4000}
        />
        <Button
          type="submit"
          className={styles.composerButton}
          disabled={!draft.trim() || post.isPending}
        >
          {post.isPending ? "Sending" : "Send"}
        </Button>
      </form>
      {post.isError ? (
        <p className={styles.errorText} role="alert">
          {post.error.message}
        </p>
      ) : (
        <p className={styles.hint}>Enter sends. Shift+Enter adds a line.</p>
      )}
    </>
  );
}

function AddChannel({
  onCreated,
}: {
  onCreated: (channel: TeamChannel) => void;
}) {
  const create = useCreateTeamChannel();
  const [name, setName] = useState("");
  return (
    <form
      className={styles.addChannel}
      onSubmit={(event) => {
        event.preventDefault();
        const trimmed = name.trim();
        if (!trimmed) return;
        create.mutate(
          { name: trimmed },
          {
            onSuccess: (channel) => {
              setName("");
              onCreated(channel);
            },
          },
        );
      }}
    >
      <label htmlFor="team-new-channel" className={pageStyles.eyebrow}>
        Add a channel
      </label>
      <Input
        id="team-new-channel"
        value={name}
        onChange={(event) => setName(event.target.value)}
        placeholder="e.g. Design"
        maxLength={64}
      />
      <Button
        type="submit"
        variant="outline"
        className={styles.composerButton}
        disabled={!name.trim() || create.isPending}
      >
        Add
      </Button>
      {create.isError ? (
        <p className={styles.errorText} role="alert">
          {create.error.message}
        </p>
      ) : null}
    </form>
  );
}
