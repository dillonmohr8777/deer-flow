"use client";

import { useQueryClient, type useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
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
import { useApproveBoardReply, useSendBoardReply } from "@/core/board";
import {
  CEO_NEEDS_MY_YES_QUERY_KEY,
  useCeoFeed,
  useDailyDigest,
  useNeedsMyYes,
  usePostCeoFeedMessage,
  useRatifySeat,
  useReopenSeat,
  useSeatRoster,
  type BoardDraftAwaitingApproval,
  type CeoFeedSlug,
  type DailyDigest,
  type SeatAwaitingRatification,
  type SeatRosterEntry,
} from "@/core/ceo-desk";
import { useCeoDeskEnabled, useMomentumInternalEnabled } from "@/core/features";
import { cn } from "@/lib/utils";

import {
  draftClientLabel,
  formatSeatBurn,
  formatStamp,
  seatKpiLabel,
  seatStatusLabel,
  seatStatusTone,
} from "./ceo-desk-data";

import styles from "./ceo-desk.module.css";

type QueryResult<T> = ReturnType<typeof useQuery<T>>;

/**
 * CEO Desk: the owner/admin's daily digest, needs-my-yes queue and agent
 * seat roster in one place. Renders only when features.ceo.enabled (an
 * owner/admin of the active organization); /api/ceo's routes enforce the
 * same rule and 403 everyone else.
 */
export function CeoDesk() {
  const { enabled, isLoading } = useCeoDeskEnabled();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !enabled) router.replace("/workspace/command-center");
  }, [enabled, isLoading, router]);

  useEffect(() => {
    if (enabled) document.title = "CEO Desk | MomoBot";
  }, [enabled]);

  if (!enabled) {
    return <WorkingState label="Loading" className="m-8" />;
  }
  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className={pageStyles.page}>
        <CeoDeskBody />
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

export function CeoDeskBody() {
  const digest = useDailyDigest();
  const needsMyYes = useNeedsMyYes();
  const seats = useSeatRoster();
  // The feeds are Momentum's own #exec/#fleet chatter, never a client
  // workspace's (f189) -- the backend 404s a non-staff caller, so the
  // frontend never even asks on a workspace where Team itself is hidden.
  const { enabled: feedsEnabled } = useMomentumInternalEnabled();

  return (
    <div className={styles.frame} data-testid="ceo-desk">
      <header>
        <p className={pageStyles.eyebrow}>Owner and admin only</p>
        <h1 className="mt-1">CEO Desk</h1>
        <p className={cn(pageStyles.lede, "mt-1")}>
          What shipped, what&apos;s stuck, and what needs your yes.
        </p>
      </header>
      <DigestSection digest={digest} />
      <NeedsMyYesSection needsMyYes={needsMyYes} />
      <SeatRosterSection seats={seats} />
      {feedsEnabled ? <FeedsSection /> : null}
    </div>
  );
}

function DigestSection({
  digest,
}: {
  digest: QueryResult<DailyDigest | null>;
}) {
  return (
    <section className={styles.section} aria-labelledby="ceo-digest-heading">
      <h2 id="ceo-digest-heading" className={styles.sectionTitle}>
        Today
      </h2>
      {digest.isError ? (
        <ErrorState
          message="Couldn't load today's digest."
          detail={digest.error.message}
          action={
            <Button
              variant="outline"
              size="sm"
              onClick={() => void digest.refetch()}
            >
              Try again
            </Button>
          }
        />
      ) : digest.isLoading ? (
        <WorkingState label="Loading digest" />
      ) : digest.data ? (
        <div className={styles.digest}>
          <p className={styles.digestText}>{digest.data.digest_text}</p>
          <dl className={styles.digestStats}>
            <div className={styles.digestStat}>
              <dt className={styles.digestStatLabel}>Shipped</dt>
              <dd className={styles.digestStatValue}>
                {digest.data.shipped_count}
              </dd>
            </div>
            <div className={styles.digestStat}>
              <dt className={styles.digestStatLabel}>Stuck</dt>
              <dd className={styles.digestStatValue}>
                {digest.data.stuck_count}
              </dd>
            </div>
            <div className={styles.digestStat}>
              <dt className={styles.digestStatLabel}>Replies waiting</dt>
              <dd className={styles.digestStatValue}>
                {digest.data.needs_my_yes_drafts}
              </dd>
            </div>
            <div className={styles.digestStat}>
              <dt className={styles.digestStatLabel}>Seats waiting</dt>
              <dd className={styles.digestStatValue}>
                {digest.data.needs_my_yes_ratifications}
              </dd>
            </div>
          </dl>
          <time
            className={styles.digestStamp}
            dateTime={digest.data.created_at}
          >
            Generated {formatStamp(digest.data.created_at)}
          </time>
        </div>
      ) : (
        <EmptyState momo="lead" title="No digest yet">
          The daily digest generates automatically each morning once it is
          turned on for this workspace.
        </EmptyState>
      )}
    </section>
  );
}

function NeedsMyYesSection({
  needsMyYes,
}: {
  needsMyYes: QueryResult<{
    board_drafts: BoardDraftAwaitingApproval[];
    seat_ratifications: SeatAwaitingRatification[];
  }>;
}) {
  return (
    <section
      className={styles.section}
      aria-labelledby="ceo-needs-my-yes-heading"
    >
      <h2 id="ceo-needs-my-yes-heading" className={styles.sectionTitle}>
        Needs your yes
      </h2>
      {needsMyYes.isError ? (
        <ErrorState
          message="Couldn't load what needs your yes."
          detail={needsMyYes.error.message}
          action={
            <Button
              variant="outline"
              size="sm"
              onClick={() => void needsMyYes.refetch()}
            >
              Try again
            </Button>
          }
        />
      ) : needsMyYes.isLoading ? (
        <WorkingState label="Loading" />
      ) : needsMyYes.data?.board_drafts.length === 0 &&
        needsMyYes.data.seat_ratifications.length === 0 ? (
        <EmptyState momo="verifier" title="Nothing waiting on you">
          Board drafts and seat ratifications will show up here as they come in.
        </EmptyState>
      ) : (
        <div className={styles.cardList}>
          {needsMyYes.data?.board_drafts.map((draft) => (
            <BoardDraftCard key={draft.thread_id} draft={draft} />
          ))}
          {needsMyYes.data?.seat_ratifications.map((claim) => (
            <SeatClaimCard key={claim.seat_id} claim={claim} />
          ))}
        </div>
      )}
    </section>
  );
}

function BoardDraftCard({ draft }: { draft: BoardDraftAwaitingApproval }) {
  const approve = useApproveBoardReply();
  const send = useSendBoardReply();
  const queryClient = useQueryClient();
  const subject = draft.subject || "(no subject)";
  // Both actions land here rather than in useApproveBoardReply/useSendBoardReply
  // themselves: those hooks only invalidate board query keys, so the
  // needs-my-yes queue also needs to drop this thread once it moves on
  // (same pattern as f178's approve fix). The digest is a stored snapshot
  // the background sweep writes once a day (GET /api/ceo/digest never
  // regenerates it), so invalidating its query key here would only refetch
  // the same unchanged row -- there is nothing to invalidate.
  const onThreadAdvanced = () => {
    void queryClient.invalidateQueries({
      queryKey: CEO_NEEDS_MY_YES_QUERY_KEY,
    });
  };
  const error = approve.error ?? send.error;
  return (
    <div className={styles.card}>
      <div className={styles.cardInfo}>
        <p className={styles.cardSubject}>{subject}</p>
        <p className={styles.cardMeta}>
          {draftClientLabel(draft.client_id)} &middot; {draft.kind} &middot;{" "}
          <time dateTime={draft.updated_at}>
            {formatStamp(draft.updated_at)}
          </time>
        </p>
        {draft.draft_body ? (
          <Textarea
            value={draft.draft_body}
            readOnly
            aria-readonly="true"
            aria-label={`Momo's draft reply to ${subject}`}
            rows={3}
            className={styles.cardDraftBody}
          />
        ) : null}
        {error ? (
          <p className={styles.errorText} role="alert">
            {error.message}
          </p>
        ) : null}
      </div>
      <div className={styles.cardActions}>
        {draft.status === "approved" ? (
          <Button
            size="sm"
            disabled={!draft.draft_body || send.isPending}
            aria-label={`Send reply to ${subject}`}
            onClick={() =>
              send.mutate(
                { threadId: draft.thread_id, body: draft.draft_body ?? "" },
                { onSuccess: onThreadAdvanced },
              )
            }
          >
            {send.isPending ? "Sending" : "Send reply"}
          </Button>
        ) : (
          <Button
            size="sm"
            disabled={approve.isPending}
            aria-label={`Approve ${subject}`}
            onClick={() =>
              approve.mutate(
                { threadId: draft.thread_id },
                { onSuccess: onThreadAdvanced },
              )
            }
          >
            {approve.isPending ? "Approving" : "Approve"}
          </Button>
        )}
        <Button variant="outline" size="sm" asChild>
          <Link href="/workspace/board">Open in Board</Link>
        </Button>
      </div>
    </div>
  );
}

function SeatClaimCard({ claim }: { claim: SeatAwaitingRatification }) {
  const ratify = useRatifySeat();
  const reopen = useReopenSeat();
  const error = ratify.error ?? reopen.error;
  return (
    <div className={styles.card}>
      <div className={styles.cardInfo}>
        <p className={styles.cardSubject}>
          {claim.seat} &middot; {claim.agent_name}
        </p>
        <p className={styles.cardMeta}>
          Claimed{" "}
          <time dateTime={claim.created_at}>
            {formatStamp(claim.created_at)}
          </time>
        </p>
        {error ? (
          <p className={styles.errorText} role="alert">
            {error.message}
          </p>
        ) : null}
      </div>
      <div className={styles.cardActions}>
        <Button
          size="sm"
          disabled={ratify.isPending || reopen.isPending}
          aria-label={`Ratify ${claim.seat} for ${claim.agent_name}`}
          onClick={() => ratify.mutate(claim.seat_id)}
        >
          {ratify.isPending ? "Ratifying" : "Ratify"}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={ratify.isPending || reopen.isPending}
          aria-label={`Reopen ${claim.seat} for ${claim.agent_name}`}
          onClick={() => reopen.mutate(claim.seat_id)}
        >
          {reopen.isPending ? "Reopening" : "Reopen"}
        </Button>
      </div>
    </div>
  );
}

function SeatRosterSection({
  seats,
}: {
  seats: QueryResult<SeatRosterEntry[]>;
}) {
  return (
    <section
      className={styles.section}
      aria-labelledby="ceo-seat-roster-heading"
    >
      <h2 id="ceo-seat-roster-heading" className={styles.sectionTitle}>
        Seat roster
      </h2>
      {seats.isError ? (
        <ErrorState
          message="Couldn't load the seat roster."
          detail={seats.error.message}
          action={
            <Button
              variant="outline"
              size="sm"
              onClick={() => void seats.refetch()}
            >
              Try again
            </Button>
          }
        />
      ) : seats.isLoading ? (
        <WorkingState label="Loading seats" />
      ) : !seats.data || seats.data.length === 0 ? (
        <EmptyState momo="lead" title="No seats yet">
          Titled agents will appear here once one claims a seat in #exec.
        </EmptyState>
      ) : (
        <div className={styles.rosterTableWrap}>
          <table className={styles.rosterTable}>
            <thead>
              <tr>
                <th scope="col">Seat</th>
                <th scope="col">Agent</th>
                <th scope="col">KPI</th>
                <th scope="col">Status</th>
                <th scope="col">Budget burn</th>
              </tr>
            </thead>
            <tbody>
              {seats.data.map((seat) => (
                <tr key={seat.seat_id}>
                  <td>{seat.seat}</td>
                  <td>{seat.agent_name}</td>
                  <td>{seatKpiLabel(seat)}</td>
                  <td>
                    <StatusTag tone={seatStatusTone(seat)}>
                      {seatStatusLabel(seat)}
                    </StatusTag>
                  </td>
                  <td>{formatSeatBurn(seat)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

const FEED_SLUGS: readonly CeoFeedSlug[] = ["exec", "fleet"];

/**
 * Live #exec and #fleet Team Board feeds, read and reply, right on the CEO
 * Desk. Author names are resolved server-side (f193): the feed endpoint
 * itself returns each message's `author_display_name` ("You", the author's
 * own name, or "Momentum" for a fleet agent's signing user id), so this
 * never depends on the separate `/api/team/members` lookup.
 */
function FeedsSection() {
  return (
    <section className={styles.section} aria-labelledby="ceo-feeds-heading">
      <h2 id="ceo-feeds-heading" className={styles.sectionTitle}>
        Live feeds
      </h2>
      <div className={styles.feedGrid}>
        {FEED_SLUGS.map((slug) => (
          <FeedPanel key={slug} slug={slug} />
        ))}
      </div>
    </section>
  );
}

function FeedPanel({ slug }: { slug: CeoFeedSlug }) {
  const feed = useCeoFeed(slug);
  const post = usePostCeoFeedMessage(slug);
  const [draft, setDraft] = useState("");
  const listRef = useRef<HTMLOListElement>(null);
  const count = feed.data?.messages.length ?? 0;

  useEffect(() => {
    // f190: scroll only this panel's own list, not scrollIntoView, which
    // walks every scrollable ancestor including the page -- a new message
    // arriving from the 15s poll must never yank the viewport away from
    // the digest or needs-my-yes queue above.
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [count]);

  const send = () => {
    const body = draft.trim();
    if (!body || post.isPending) return;
    post.mutate(body, { onSuccess: () => setDraft("") });
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

  return (
    <div className={styles.feedPanel} data-testid={`ceo-feed-${slug}`}>
      <h3 className={styles.feedTitle}>#{slug}</h3>
      {feed.isError ? (
        <ErrorState
          message={`Couldn't load #${slug}.`}
          detail={feed.error.message}
          action={
            <Button
              variant="outline"
              size="sm"
              onClick={() => void feed.refetch()}
            >
              Try again
            </Button>
          }
        />
      ) : feed.isLoading ? (
        <WorkingState label={`Loading #${slug}`} />
      ) : feed.data && !feed.data.exists ? (
        <p className={styles.hint}>
          No #{slug} channel yet. Create it once from Team.
        </p>
      ) : count === 0 ? (
        <EmptyState momo="verifier" title="Nothing here yet">
          Replies in #{slug} will show up here as they come in.
        </EmptyState>
      ) : (
        <ol ref={listRef} className={styles.feedMessages} aria-live="polite">
          {feed.data?.messages.map((message) => (
            <li key={message.id} className={styles.feedMessage}>
              <span className={styles.feedMessageHead}>
                <span className={styles.author}>
                  {message.author_display_name}
                </span>
                <time
                  className={styles.feedStamp}
                  dateTime={message.created_at}
                >
                  {formatStamp(message.created_at)}
                </time>
              </span>
              {message.body}
            </li>
          ))}
        </ol>
      )}
      {feed.data?.exists ? (
        <form
          className={styles.feedComposer}
          onSubmit={(event) => {
            event.preventDefault();
            send();
          }}
        >
          <label htmlFor={`ceo-feed-composer-${slug}`} className="sr-only">
            Message #{slug}
          </label>
          <Textarea
            id={`ceo-feed-composer-${slug}`}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={onKeyDown}
            placeholder={`Message #${slug}`}
            rows={2}
            maxLength={4000}
          />
          <Button
            type="submit"
            size="sm"
            disabled={!draft.trim() || post.isPending}
          >
            {post.isPending ? "Sending" : "Send"}
          </Button>
        </form>
      ) : null}
      {post.isError ? (
        <p className={styles.errorText} role="alert">
          {post.error.message}
        </p>
      ) : null}
    </div>
  );
}
