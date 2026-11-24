"use client";

import { ExternalLink } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  EmptyState,
  ErrorState,
  FilterGroup,
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
  useCreateReviewDoc,
  useReportConnectors,
  useReportLeads,
  useReportSummary,
  useReviewDocs,
  useUpdateReviewDoc,
  type LeadCategory,
  type MatchStatus,
  type ReportingPeriod,
  type ReviewDoc,
  type ReviewDocStatus,
} from "@/core/reports";
import { cn } from "@/lib/utils";

import {
  CONFIDENCE_LABEL,
  CONNECTOR_LABEL,
  connectorStatusMeta,
  dataStateMeta,
  formatIsoDate,
  formatIsoDateTime,
  formatLeadCount,
  LEAD_CATEGORY_LABEL,
  LEAD_TYPE_OPTIONS,
  MATCH_STATUS_OPTIONS,
  matchStatusMeta,
  PERIOD_LABEL,
  PERIOD_OPTIONS,
  reviewStatusMeta,
  validateGoogleDocUrlClient,
} from "./reports-data";

import styles from "./reports.module.css";

/** Workspace-scoped Reports & Leads view for account managers and staff. */
export function Reports() {
  useEffect(() => {
    document.title = "Reports & Leads | MomoBot";
  }, []);
  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className={pageStyles.page}>
        <ReportsBody />
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

export function ReportsBody() {
  const [period, setPeriod] = useState<ReportingPeriod>("last_30d");
  const [leadTypeFilter, setLeadTypeFilter] = useState<LeadCategory | "all">(
    "all",
  );
  const [matchFilter, setMatchFilter] = useState<MatchStatus | "all">("all");

  const summary = useReportSummary(period);
  const leads = useReportLeads({
    period,
    leadType: leadTypeFilter === "all" ? undefined : leadTypeFilter,
    matchStatus: matchFilter === "all" ? undefined : matchFilter,
  });
  const connectors = useReportConnectors();
  const reviewDocs = useReviewDocs();

  const kpis = summary.data?.kpis;
  const activeDataState = kpis?.data_state ?? "pending";
  const kpiStateBadge = dataStateMeta(activeDataState);

  return (
    <div className={styles.frame} data-testid="reports-page">
      <header className={styles.headerRow}>
        <div>
          <p className={pageStyles.eyebrow}>Reports &amp; Leads</p>
          <h1 className="mt-1">Reports &amp; Leads</h1>
          <p className={cn(pageStyles.lede, "mt-1")}>
            Verified lead totals, named-lead match-back, read-only connector
            health, and Google Doc report approvals for the active workspace.
          </p>
        </div>
        {summary.data?.workspace_name ? (
          <p className={styles.workspaceBadge} data-testid="reports-workspace">
            Workspace: {summary.data.workspace_name}
          </p>
        ) : null}
      </header>

      <FilterGroup
        label="Reporting period"
        showLabel
        value={period}
        onChange={setPeriod}
        options={PERIOD_OPTIONS}
      />

      <section aria-label="Verified lead summary">
        {summary.isError ? (
          <ErrorState
            message="Could not load verified lead summary."
            detail={
              summary.error instanceof Error ? summary.error.message : undefined
            }
            action={
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  void summary.refetch();
                }}
              >
                Retry
              </Button>
            }
          />
        ) : summary.isLoading || !kpis ? (
          <WorkingState label="Loading verified lead summary" />
        ) : (
          <div className={styles.kpiBand} data-testid="reports-kpi-strip">
            <div className={cn(styles.heroSheet, pageStyles.sheet)}>
              <div className={styles.heroTop}>
                <span className={pageStyles.eyebrow}>Total verified leads</span>
                <StatusTag tone={kpiStateBadge.tone}>
                  {kpiStateBadge.label}
                </StatusTag>
              </div>
              <p className={styles.heroValue} data-testid="kpi-total-leads">
                {formatLeadCount(kpis.total_leads, kpis.data_state)}
              </p>
              <p className={styles.heroNote}>
                Integer lead counts only: forms, calls, and{" "}
                {kpis.appointment_label.toLowerCase()}. Clicks, impressions, and
                sessions are excluded.
              </p>
            </div>

            <div className={styles.splitGrid}>
              <div className={cn(styles.splitCell, pageStyles.sheet)}>
                <span className={pageStyles.eyebrow}>Forms</span>
                <p className={styles.splitValue} data-testid="kpi-forms">
                  {formatLeadCount(kpis.forms, kpis.data_state)}
                </p>
                <span className={styles.splitSub}>Verified submissions</span>
              </div>

              <div className={cn(styles.splitCell, pageStyles.sheet)}>
                <span className={pageStyles.eyebrow}>Calls</span>
                <p className={styles.splitValue} data-testid="kpi-calls">
                  {formatLeadCount(kpis.calls, kpis.data_state)}
                </p>
                <span className={styles.splitSub}>Tracked inbound calls</span>
              </div>

              <div className={cn(styles.splitCell, pageStyles.sheet)}>
                <span className={pageStyles.eyebrow}>
                  {kpis.appointment_label}
                </span>
                <p className={styles.splitValue} data-testid="kpi-appointments">
                  {formatLeadCount(kpis.appointments, kpis.data_state)}
                </p>
                <span className={styles.splitSub}>Vertical booking metric</span>
              </div>

              <div className={cn(styles.splitCell, pageStyles.sheet)}>
                <span className={pageStyles.eyebrow}>Matched leads</span>
                <p className={styles.splitValue} data-testid="kpi-matched">
                  {formatLeadCount(kpis.matched_leads, kpis.data_state)}
                </p>
                <span className={styles.splitSub}>Named-lead match-back</span>
              </div>
            </div>
          </div>
        )}
      </section>

      <section
        className={cn(styles.section, pageStyles.sheet)}
        aria-labelledby="leads-section-heading"
      >
        <div className={styles.sectionHeader}>
          <h2 id="leads-section-heading" className={styles.sectionTitle}>
            Named-lead match-back &amp; source attribution
          </h2>
          {leads.data ? (
            <span className={pageStyles.eyebrow}>
              {leads.data.total_count} recorded in {PERIOD_LABEL[period]}
            </span>
          ) : null}
        </div>

        <div className={styles.filterRow}>
          <FilterGroup
            label="Lead type"
            showLabel
            value={leadTypeFilter}
            onChange={setLeadTypeFilter}
            options={LEAD_TYPE_OPTIONS}
          />
          <FilterGroup
            label="Match status"
            showLabel
            value={matchFilter}
            onChange={setMatchFilter}
            options={MATCH_STATUS_OPTIONS}
          />
        </div>

        {leads.isError ? (
          <ErrorState
            message="Could not load verified leads."
            detail={
              leads.error instanceof Error ? leads.error.message : undefined
            }
            action={
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  void leads.refetch();
                }}
              >
                Retry
              </Button>
            }
          />
        ) : leads.isLoading ? (
          <WorkingState label="Loading named-lead match-back records" />
        ) : !leads.data || leads.data.leads.length === 0 ? (
          leads.data?.data_state === "pending" ||
          leads.data?.data_state === "unavailable" ? (
            <EmptyState
              momo="analytics"
              title={
                leads.data.data_state === "unavailable"
                  ? "Lead connectors are currently unavailable"
                  : "Lead connectors are pending setup"
              }
            >
              Connect at least one read-only lead source below to populate
              verified named-lead rows. Missing feeds are never counted as zero.
            </EmptyState>
          ) : (
            <EmptyState
              momo="analytics"
              title="No matching leads in this period"
            >
              Connected feeds reported no verified lead rows matching the
              selected period and filters.
            </EmptyState>
          )
        ) : (
          <div
            tabIndex={0}
            role="region"
            aria-labelledby="reports-leads-caption"
            className={styles.tableWrapper}
          >
            <table className={styles.leadsTable}>
              <caption
                id="reports-leads-caption"
                className={styles.tableCaption}
              >
                Verified lead records for {PERIOD_LABEL[period]}
              </caption>
              <thead>
                <tr>
                  <th scope="col">Lead</th>
                  <th scope="col">Type</th>
                  <th scope="col">Channel &amp; campaign</th>
                  <th scope="col">Source</th>
                  <th scope="col">Match-back</th>
                  <th scope="col">Date</th>
                </tr>
              </thead>
              <tbody>
                {leads.data.leads.map((lead) => {
                  const matchMeta = matchStatusMeta(lead.match_status);
                  return (
                    <tr key={lead.id}>
                      <th scope="row">
                        <span>{lead.lead_name}</span>
                        {lead.notes ? (
                          <span className={styles.leadSubline}>
                            {lead.notes}
                          </span>
                        ) : null}
                      </th>
                      <td>{LEAD_CATEGORY_LABEL[lead.lead_type]}</td>
                      <td>
                        <span>{lead.channel}</span>
                        {lead.campaign_name ? (
                          <span className={styles.leadSubline}>
                            {lead.campaign_name}
                          </span>
                        ) : null}
                      </td>
                      <td>
                        {CONNECTOR_LABEL[lead.source_connector] ??
                          lead.source_connector}
                      </td>
                      <td>
                        <StatusTag tone={matchMeta.tone}>
                          {matchMeta.label}
                        </StatusTag>
                        <span className={styles.leadSubline}>
                          {CONFIDENCE_LABEL[lead.match_confidence]}
                        </span>
                      </td>
                      <td>{formatIsoDate(lead.occurred_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className={styles.lowerGrid}>
        <section
          className={cn(styles.section, pageStyles.sheet)}
          aria-labelledby="connectors-section-heading"
          data-testid="connector-health-panel"
        >
          <div className={styles.sectionHeader}>
            <h2 id="connectors-section-heading" className={styles.sectionTitle}>
              Read connector health
            </h2>
            <span className={pageStyles.eyebrow}>Plane 0 read-only</span>
          </div>

          {connectors.isError ? (
            <ErrorState
              message="Could not load connector health."
              detail={
                connectors.error instanceof Error
                  ? connectors.error.message
                  : undefined
              }
              action={
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    void connectors.refetch();
                  }}
                >
                  Retry
                </Button>
              }
            />
          ) : connectors.isLoading ? (
            <WorkingState label="Checking connector health" />
          ) : (
            <ul className={styles.connectorList}>
              {(connectors.data?.connectors ?? []).map((connector) => {
                const statusMeta = connectorStatusMeta(connector.status);
                return (
                  <li
                    key={connector.connector_key}
                    className={styles.connectorRow}
                    data-testid={`connector-${connector.connector_key}`}
                  >
                    <div className={styles.connectorTop}>
                      <span className={styles.connectorName}>
                        {connector.display_name}
                      </span>
                      <StatusTag tone={statusMeta.tone}>
                        {statusMeta.label}
                      </StatusTag>
                    </div>
                    <p className={styles.heroNote}>{connector.detail}</p>
                    <div className={styles.connectorMeta}>
                      <span>
                        Account:{" "}
                        {connector.external_account_ref ?? "Not linked"}
                      </span>
                      <span>
                        Last sync:{" "}
                        {formatIsoDateTime(
                          connector.last_synced_at,
                          "Not synced yet",
                        )}
                      </span>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section
          className={cn(styles.section, pageStyles.sheet)}
          aria-labelledby="review-docs-section-heading"
          data-testid="review-docs-panel"
        >
          <div className={styles.sectionHeader}>
            <h2
              id="review-docs-section-heading"
              className={styles.sectionTitle}
            >
              Google Doc report review
            </h2>
            <span className={pageStyles.eyebrow}>
              {reviewDocs.data?.review_docs.length ?? 0} attached
            </span>
          </div>

          <AttachReviewDocForm period={period} />

          {reviewDocs.isError ? (
            <ErrorState
              message="Could not load review documents."
              detail={
                reviewDocs.error instanceof Error
                  ? reviewDocs.error.message
                  : undefined
              }
              action={
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    void reviewDocs.refetch();
                  }}
                >
                  Retry
                </Button>
              }
            />
          ) : reviewDocs.isLoading ? (
            <WorkingState label="Loading Google Doc reviews" />
          ) : !reviewDocs.data || reviewDocs.data.review_docs.length === 0 ? (
            <EmptyState momo="verifier" title="No report docs attached yet">
              Attach a Google Doc link above to start a timestamped review and
              approval trail for this workspace.
            </EmptyState>
          ) : (
            <div className={styles.reviewDocList}>
              {reviewDocs.data.review_docs.map((doc) => (
                <ReviewDocCard key={doc.id} doc={doc} />
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function AttachReviewDocForm({ period }: { period: ReportingPeriod }) {
  const titleId = useId();
  const titleHintId = useId();
  const titleErrorId = useId();
  const urlId = useId();
  const urlHintId = useId();
  const urlErrorId = useId();

  const [title, setTitle] = useState("");
  const [docUrl, setDocUrl] = useState("");
  const [touchedTitle, setTouchedTitle] = useState(false);
  const [touchedUrl, setTouchedUrl] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [liveAnnouncement, setLiveAnnouncement] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);

  const titleRef = useRef<HTMLInputElement>(null);
  const urlRef = useRef<HTMLInputElement>(null);
  const createMutation = useCreateReviewDoc();

  const titleError =
    touchedTitle || submitted
      ? title.trim()
        ? null
        : "Enter a report title before attaching."
      : null;
  const urlError =
    touchedUrl || submitted ? validateGoogleDocUrlClient(docUrl) : null;

  const announce = (message: string) => {
    setLiveAnnouncement("");
    window.setTimeout(() => {
      setLiveAnnouncement(message);
    }, 50);
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    setSubmitError(null);

    const nextTitleError = title.trim()
      ? null
      : "Enter a report title before attaching.";
    const nextUrlError = validateGoogleDocUrlClient(docUrl);

    if (nextTitleError) {
      titleRef.current?.focus();
      announce(`Report title: ${nextTitleError}`);
      return;
    }
    if (nextUrlError) {
      urlRef.current?.focus();
      announce(`Google Doc link: ${nextUrlError}`);
      return;
    }

    try {
      await createMutation.mutateAsync({
        title: title.trim(),
        doc_url: docUrl.trim(),
        period_key: period,
      });
      setTitle("");
      setDocUrl("");
      setTouchedTitle(false);
      setTouchedUrl(false);
      setSubmitted(false);
      announce("Report document attached for review.");
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Could not attach Google Doc for review.";
      setSubmitError(message);
      announce(message);
    }
  };

  return (
    <form
      className={styles.reviewForm}
      onSubmit={(event) => {
        void handleSubmit(event);
      }}
      noValidate
    >
      <div className={styles.field}>
        <label htmlFor={titleId} className={styles.fieldLabel}>
          Report title
        </label>
        <span id={titleHintId} className={styles.fieldHint}>
          Example: Monthly Performance Report for {PERIOD_LABEL[period]}
        </span>
        <Input
          ref={titleRef}
          id={titleId}
          name="title"
          required
          maxLength={255}
          value={title}
          onChange={(event) => {
            setTitle(event.target.value);
            if (submitError) setSubmitError(null);
          }}
          onBlur={() => {
            setTouchedTitle(true);
            if (!title.trim()) {
              announce("Report title: Enter a report title before attaching.");
            }
          }}
          aria-invalid={titleError ? "true" : "false"}
          aria-describedby={
            titleError ? `${titleHintId} ${titleErrorId}` : titleHintId
          }
          className={cn(
            styles.reviewInput,
            titleError && styles.userInvalidFallback,
          )}
          placeholder="Monthly Performance Report"
        />
        <div
          id={titleErrorId}
          className={cn(
            styles.fieldError,
            titleError && styles.fieldErrorVisible,
          )}
        >
          {titleError ? `Error: ${titleError}` : ""}
        </div>
      </div>

      <div className={styles.field}>
        <label htmlFor={urlId} className={styles.fieldLabel}>
          Google Doc URL
        </label>
        <span id={urlHintId} className={styles.fieldHint}>
          Format: https://docs.google.com/document/d/...
        </span>
        <Input
          ref={urlRef}
          id={urlId}
          name="doc_url"
          type="url"
          required
          value={docUrl}
          onChange={(event) => {
            setDocUrl(event.target.value);
            if (submitError) setSubmitError(null);
          }}
          onBlur={() => {
            setTouchedUrl(true);
            const msg = validateGoogleDocUrlClient(docUrl);
            if (msg) announce(`Google Doc link: ${msg}`);
          }}
          aria-invalid={urlError ? "true" : "false"}
          aria-describedby={urlError ? `${urlHintId} ${urlErrorId}` : urlHintId}
          className={cn(
            styles.reviewInput,
            urlError && styles.userInvalidFallback,
          )}
          placeholder="https://docs.google.com/document/d/..."
        />
        <div
          id={urlErrorId}
          className={cn(
            styles.fieldError,
            urlError && styles.fieldErrorVisible,
          )}
        >
          {urlError ? `Error: ${urlError}` : ""}
        </div>
      </div>

      {submitError ? (
        <p
          role="alert"
          className={cn(styles.fieldError, styles.fieldErrorVisible)}
        >
          Error: {submitError}
        </p>
      ) : null}

      <div className={styles.reviewActions}>
        <Button type="submit" size="sm" disabled={createMutation.isPending}>
          {createMutation.isPending ? "Attaching..." : "Attach for review"}
        </Button>
        <span className={styles.fieldHint}>
          Period tagged: {PERIOD_LABEL[period]}
        </span>
      </div>

      <div aria-live="polite" className={styles.visuallyHidden}>
        {liveAnnouncement}
      </div>
    </form>
  );
}

function ReviewDocCard({ doc }: { doc: ReviewDoc }) {
  const commentId = useId();
  const [commentText, setCommentText] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const updateMutation = useUpdateReviewDoc();
  const statusMeta = reviewStatusMeta(doc.status);

  const runUpdate = async (next: {
    status?: ReviewDocStatus;
    comment?: string;
  }) => {
    setActionError(null);
    try {
      await updateMutation.mutateAsync({ docId: doc.id, input: next });
      if (next.comment) {
        setCommentText("");
      }
    } catch (error) {
      setActionError(
        error instanceof Error
          ? error.message
          : "Could not update review document.",
      );
    }
  };

  return (
    <article
      className={styles.reviewDocCard}
      data-testid={`review-doc-${doc.id}`}
    >
      <div className={styles.reviewDocHeader}>
        <div>
          <a
            href={doc.doc_url}
            target="_blank"
            rel="noopener noreferrer"
            className={styles.reviewDocLink}
          >
            {doc.title}
            <ExternalLink
              aria-hidden="true"
              className="ml-1 inline-block size-3.5 align-text-bottom"
            />
          </a>
          <p className={styles.commentMeta}>
            Period: {PERIOD_LABEL[doc.period_key]} | Attached{" "}
            {formatIsoDateTime(doc.created_at, "just now")}
          </p>
        </div>
        <StatusTag tone={statusMeta.tone}>{statusMeta.label}</StatusTag>
      </div>

      {doc.comments.length > 0 ? (
        <ul className={styles.commentList} aria-label="Review comments">
          {doc.comments.map((item) => (
            <li key={item.id} className={styles.commentItem}>
              <p>{item.body}</p>
              <span className={styles.commentMeta}>
                {item.author_label} | {formatIsoDateTime(item.created_at, "")}
              </span>
            </li>
          ))}
        </ul>
      ) : null}

      <div className={styles.field}>
        <label htmlFor={commentId} className={styles.fieldLabel}>
          Review note
        </label>
        <Textarea
          id={commentId}
          rows={2}
          value={commentText}
          onChange={(event) => {
            setCommentText(event.target.value);
            if (actionError) setActionError(null);
          }}
          placeholder="Add a timestamped review comment or edit request"
        />
      </div>

      {actionError ? (
        <p
          role="alert"
          className={cn(styles.fieldError, styles.fieldErrorVisible)}
        >
          Error: {actionError}
        </p>
      ) : null}

      <div className={styles.reviewActions}>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={updateMutation.isPending || !commentText.trim()}
          onClick={() => {
            void runUpdate({ comment: commentText.trim() });
          }}
        >
          Add comment
        </Button>
        <Button
          type="button"
          size="sm"
          disabled={updateMutation.isPending || doc.status === "approved"}
          onClick={() => {
            void runUpdate({
              status: "approved",
              comment: commentText.trim() || undefined,
            });
          }}
        >
          Approve
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={updateMutation.isPending || doc.status === "needs_edits"}
          onClick={() => {
            void runUpdate({
              status: "needs_edits",
              comment: commentText.trim() || undefined,
            });
          }}
        >
          Request edits
        </Button>
      </div>
    </article>
  );
}
