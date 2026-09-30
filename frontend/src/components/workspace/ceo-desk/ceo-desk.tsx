"use client";

import type { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
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
import { useApproveBoardReply } from "@/core/board";
import {
  useDailyDigest,
  useNeedsMyYes,
  useRatifySeat,
  useReopenSeat,
  useSeatRoster,
  type BoardDraftAwaitingApproval,
  type DailyDigest,
  type SeatAwaitingRatification,
  type SeatRosterEntry,
} from "@/core/ceo-desk";
import { useCeoDeskEnabled } from "@/core/features";
import { cn } from "@/lib/utils";

import {
  draftClientLabel,
  formatSeatBurn,
  formatStamp,
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

function CeoDeskBody() {
  const digest = useDailyDigest();
  const needsMyYes = useNeedsMyYes();
  const seats = useSeatRoster();

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
              <dt className={styles.digestStatLabel}>Drafts waiting</dt>
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
  return (
    <div className={styles.card}>
      <div className={styles.cardInfo}>
        <p className={styles.cardSubject}>{draft.subject || "(no subject)"}</p>
        <p className={styles.cardMeta}>
          {draftClientLabel(draft.client_id)} &middot; {draft.kind} &middot;{" "}
          <time dateTime={draft.updated_at}>
            {formatStamp(draft.updated_at)}
          </time>
        </p>
        {approve.isError ? (
          <p className={styles.errorText} role="alert">
            {approve.error.message}
          </p>
        ) : null}
      </div>
      <div className={styles.cardActions}>
        <Button
          size="sm"
          disabled={approve.isPending}
          onClick={() => approve.mutate({ threadId: draft.thread_id })}
        >
          {approve.isPending ? "Approving" : "Approve"}
        </Button>
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
          onClick={() => ratify.mutate(claim.seat_id)}
        >
          {ratify.isPending ? "Ratifying" : "Ratify"}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={ratify.isPending || reopen.isPending}
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
                  <td>{seat.kpi || "—"}</td>
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
