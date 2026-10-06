"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

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
  useApproveApproval,
  useApprovals,
  useEditApproval,
  useRejectApproval,
  type Approval,
  type ApprovalStatus,
} from "@/core/approvals";
import { cn } from "@/lib/utils";

import boardStyles from "../board/board.module.css";

import {
  STATUS_FILTERS,
  STATUS_LABEL,
  TYPE_LABEL,
  fieldsFor,
  isReadyToSend,
  statusTone,
  targetLabel,
} from "./approvals-data";

import styles from "./approvals.module.css";

/** Agents propose outbound actions; nothing runs until you approve it here. */
export function Approvals() {
  useEffect(() => {
    document.title = "Approvals | MomoBot";
  }, []);
  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className={pageStyles.page}>
        <ApprovalsBody />
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

export function ApprovalsBody() {
  const [statusFilter, setStatusFilter] = useState<ApprovalStatus | "all">(
    "pending",
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const approvals = useApprovals(
    statusFilter === "all" ? undefined : statusFilter,
  );
  const rows = useMemo(() => approvals.data ?? [], [approvals.data]);
  const selected = rows.find((row) => row.id === selectedId) ?? null;

  useEffect(() => {
    if (selectedId && !selected) setSelectedId(null);
  }, [selectedId, selected]);

  return (
    <div className={boardStyles.frame} data-testid="approvals">
      <header>
        <p className={pageStyles.eyebrow}>Approvals</p>
        <h1 className="mt-1">Approvals inbox</h1>
        <p className={cn(pageStyles.lede, "mt-1")}>
          Messages, emails and ad changes your agents want to send. Edit them,
          then approve. Nothing goes out until you do.
        </p>
      </header>
      <FilterGroup
        label="Status"
        showLabel
        value={statusFilter}
        onChange={setStatusFilter}
        options={STATUS_FILTERS}
      />
      <div className={boardStyles.layout}>
        <div className={boardStyles.list} aria-label="Proposed actions">
          {approvals.isError ? (
            <ErrorState
              message="Couldn't load approvals."
              detail={approvals.error.message}
              action={
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void approvals.refetch()}
                >
                  Try again
                </Button>
              }
            />
          ) : approvals.isLoading ? (
            <WorkingState label="Loading approvals" />
          ) : rows.length === 0 ? (
            <EmptyState momo="lead" title="Nothing here">
              {statusFilter === "pending"
                ? "Nothing is waiting on you. Proposed actions show up here."
                : "No actions with this status."}
            </EmptyState>
          ) : (
            <ul className={boardStyles.threadList}>
              {rows.map((row) => (
                <li key={row.id}>
                  <button
                    type="button"
                    className={boardStyles.threadRow}
                    aria-current={row.id === selectedId}
                    onClick={() => setSelectedId(row.id)}
                  >
                    <span className={boardStyles.threadSubject}>
                      {row.title || TYPE_LABEL[row.action_type]}
                    </span>
                    <span className={boardStyles.threadMeta}>
                      <span>{TYPE_LABEL[row.action_type]}</span>
                      <span>{row.agent_name ?? "Agent"}</span>
                    </span>
                    <StatusTag tone={statusTone(row.status)}>
                      {isReadyToSend(row)
                        ? "Ready to send"
                        : STATUS_LABEL[row.status]}
                    </StatusTag>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className={boardStyles.detail}>
          {selected ? (
            <ApprovalDetail key={selected.id} approval={selected} />
          ) : (
            <EmptyState momo="qa" title="Pick an action">
              Select an item to read, edit and approve or reject it.
            </EmptyState>
          )}
        </div>
      </div>
    </div>
  );
}

function asText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function ApprovalDetail({ approval }: { approval: Approval }) {
  const fields = fieldsFor(approval.action_type);
  const editMutation = useEditApproval();
  const approveMutation = useApproveApproval();
  const rejectMutation = useRejectApproval();

  const [target, setTarget] = useState(approval.target);
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      (fields ?? []).map((f) => [f.key, asText(approval.payload[f.key])]),
    ),
  );
  const [json, setJson] = useState(() =>
    JSON.stringify(approval.payload, null, 2),
  );

  const pending = approval.status === "pending";
  let parsed: Record<string, unknown> | null = null;
  let parseError: string | null = null;
  if (fields) {
    // Keep keys the form doesn't show (e.g. thread_ts) so an edit never drops them.
    parsed = { ...approval.payload, ...values };
  } else {
    try {
      const value: unknown = JSON.parse(json);
      if (value && typeof value === "object" && !Array.isArray(value)) {
        parsed = value as Record<string, unknown>;
      } else {
        parseError = "Payload must be a JSON object.";
      }
    } catch {
      parseError = "Payload is not valid JSON.";
    }
  }
  const dirty =
    target !== approval.target ||
    JSON.stringify(parsed) !== JSON.stringify(approval.payload);
  const busy =
    editMutation.isPending ||
    approveMutation.isPending ||
    rejectMutation.isPending;
  const error =
    editMutation.error ?? approveMutation.error ?? rejectMutation.error;

  return (
    <div className={boardStyles.threadDetail} data-testid="approval-detail">
      <header className={boardStyles.threadHead}>
        <div className="min-w-0">
          <h2>{approval.title || TYPE_LABEL[approval.action_type]}</h2>
          <p className={boardStyles.muted}>
            {TYPE_LABEL[approval.action_type]} &middot;{" "}
            {approval.agent_name ?? "Agent"} &middot;{" "}
            {new Date(approval.created_at).toLocaleString()}
          </p>
          {approval.thread_id ? (
            <Link
              className="text-sm underline"
              href={`/workspace/chats/${approval.thread_id}`}
            >
              See the conversation that proposed this
              {approval.run_id ? ` (run ${approval.run_id.slice(0, 8)})` : ""}
            </Link>
          ) : null}
        </div>
        <StatusTag tone={statusTone(approval.status)}>
          {isReadyToSend(approval)
            ? "Ready to send"
            : STATUS_LABEL[approval.status]}
        </StatusTag>
      </header>

      <div className={styles.field}>
        <label htmlFor="approval-target" className={pageStyles.eyebrow}>
          {targetLabel(approval.action_type)}
        </label>
        <Input
          id="approval-target"
          value={target}
          disabled={!pending}
          onChange={(event) => setTarget(event.target.value)}
        />
      </div>

      {fields ? (
        fields.map((field) => (
          <div className={styles.field} key={field.key}>
            <label
              htmlFor={`approval-${field.key}`}
              className={pageStyles.eyebrow}
            >
              {field.label}
            </label>
            {field.multiline ? (
              <Textarea
                id={`approval-${field.key}`}
                rows={6}
                value={values[field.key] ?? ""}
                disabled={!pending}
                onChange={(event) =>
                  setValues((prev) => ({
                    ...prev,
                    [field.key]: event.target.value,
                  }))
                }
              />
            ) : (
              <Input
                id={`approval-${field.key}`}
                value={values[field.key] ?? ""}
                disabled={!pending}
                onChange={(event) =>
                  setValues((prev) => ({
                    ...prev,
                    [field.key]: event.target.value,
                  }))
                }
              />
            )}
          </div>
        ))
      ) : (
        <div className={styles.field}>
          <label htmlFor="approval-json" className={pageStyles.eyebrow}>
            Details (JSON)
          </label>
          <Textarea
            id="approval-json"
            className={styles.mono}
            rows={8}
            value={json}
            disabled={!pending}
            onChange={(event) => setJson(event.target.value)}
          />
          {parseError ? (
            <p className={boardStyles.errorText}>{parseError}</p>
          ) : null}
        </div>
      )}

      {approval.fact_check?.claims.length ? (
        <section aria-label="Fact check" className={styles.field}>
          <p className={pageStyles.eyebrow}>
            Fact check
            {approval.fact_check.gate === "pass" ? " (all claims sourced)" : ""}
          </p>
          <ul>
            {approval.fact_check.claims.map((claim) => (
              <li key={claim.id}>
                <StatusTag
                  tone={claim.verdict === "supported" ? "ok" : "attention"}
                >
                  {claim.verdict === "supported"
                    ? "Sourced"
                    : claim.verdict === "unverifiable"
                      ? "Couldn't verify"
                      : "Unsourced"}
                </StatusTag>{" "}
                {claim.text}
                <span className={boardStyles.muted}>
                  {claim.evidence
                    ? ` Source: ${claim.evidence}`
                    : claim.reason
                      ? ` ${claim.reason}`
                      : ""}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {approval.execution_result?.note ? (
        <p className={styles.note}>{asText(approval.execution_result.note)}</p>
      ) : null}
      {approval.error ? (
        <p className={boardStyles.errorText}>{approval.error}</p>
      ) : null}
      {error ? <p className={boardStyles.errorText}>{error.message}</p> : null}

      {pending ? (
        <div className={styles.actions} aria-label="Review actions">
          <Button
            variant="outline"
            disabled={!dirty || !parsed || busy}
            onClick={() =>
              parsed &&
              editMutation.mutate({
                id: approval.id,
                edit: { target, payload: parsed },
              })
            }
          >
            {editMutation.isPending ? "Saving..." : "Save edits"}
          </Button>
          <Button
            disabled={dirty || busy}
            title={dirty ? "Save your edits first" : undefined}
            onClick={() => approveMutation.mutate({ id: approval.id })}
          >
            {approveMutation.isPending ? "Approving..." : "Approve and send"}
          </Button>
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => rejectMutation.mutate({ id: approval.id })}
          >
            {rejectMutation.isPending ? "Rejecting..." : "Reject"}
          </Button>
          {dirty ? (
            <p className={boardStyles.muted}>
              Save your edits before approving.
            </p>
          ) : null}
        </div>
      ) : approval.decided_at ? (
        <p className={boardStyles.muted}>
          {STATUS_LABEL[approval.status]}{" "}
          {new Date(approval.decided_at).toLocaleString()}
        </p>
      ) : null}
    </div>
  );
}
