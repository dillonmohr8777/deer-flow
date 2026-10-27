"use client";

import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { format } from "date-fns";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  getWorkPlan,
  getWorkPlanParticipants,
  putWorkPlan,
  validateWorkPlan,
  type WorkPlan,
  type WorkPlanRecord,
} from "@/core/client-portal/work-plan";

type Props = {
  userId: string;
  workspace: string;
  clientId: string;
  requestId: string;
  requests: { id: string; subject: string }[];
  requestsLoading?: boolean;
  requestsError?: string;
  hasMoreRequests?: boolean;
};

const control =
  "min-h-11 w-full min-w-0 rounded-md border bg-background px-3 text-base";
const emptyPlan: WorkPlan = {
  outcome: "",
  assignee_user_id: null,
  due_at: null,
  dependency_thread_ids: [],
  verifier_user_id: null,
  status: "planned",
  next_action: "",
  evidence_refs: [],
};

export function InternalWorkPlan(props: Props) {
  return (
    <ScopedWorkPlan
      key={JSON.stringify([
        props.userId,
        props.workspace,
        props.clientId,
        props.requestId,
      ])}
      {...props}
    />
  );
}

function ScopedWorkPlan(props: Props) {
  const query = useQuery({
    queryKey: [
      "portal",
      props.userId,
      props.workspace,
      "work-plan",
      props.clientId,
      props.requestId,
    ],
    queryFn: ({ signal }) =>
      getWorkPlan({
        workspace: props.workspace,
        requestId: props.requestId,
        signal,
      }),
    gcTime: 0,
    staleTime: Infinity,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  return (
    <section
      aria-label="Internal work plan"
      className="mt-6 min-w-0 space-y-3 border-t pt-4 [overflow-wrap:anywhere]"
    >
      <h3 className="text-lg font-medium">Internal work plan</h3>
      <p className="text-muted-foreground text-sm">
        Staff recorded, unverified. Saving records this plan only. It does not
        start work, send a reply, or verify completion.
      </p>
      {query.data ? (
        <PlanForm
          {...props}
          initialRecord={query.data}
          reload={async () => {
            const result = await query.refetch();
            if (result.isError) throw result.error;
            return result.data;
          }}
        />
      ) : (
        <>
          <p role={query.error ? "alert" : "status"}>
            {query.error?.message ?? "Loading work plan…"}
          </p>
          {query.error && (
            <Button
              variant="outline"
              className="min-h-11"
              disabled={query.isFetching}
              onClick={() => void query.refetch()}
            >
              Reload plan
            </Button>
          )}
        </>
      )}
    </section>
  );
}

function PlanForm({
  initialRecord,
  reload,
  ...props
}: Props & {
  initialRecord: WorkPlanRecord;
  reload: () => Promise<WorkPlanRecord | undefined>;
}) {
  const queryClient = useQueryClient();
  const [record, setRecord] = useState(initialRecord);
  const [plan, setPlan] = useState<WorkPlan>(initialRecord.plan ?? emptyPlan);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const directory = useInfiniteQuery({
    queryKey: [
      "portal",
      props.userId,
      props.workspace,
      "work-plan-participants",
      props.clientId,
      props.requestId,
      record.revision,
    ],
    initialPageParam: {
      cursor: null as string | null,
      userIds: [] as string[],
      cursors: [] as string[],
    },
    queryFn: async ({ signal, pageParam }) => {
      const page = await getWorkPlanParticipants({
        workspace: props.workspace,
        requestId: props.requestId,
        signal,
        cursor: pageParam.cursor,
      });
      if (
        page.items.some((item) => pageParam.userIds.includes(item.user_id)) ||
        (page.next_cursor !== null &&
          pageParam.cursors.includes(page.next_cursor))
      ) {
        throw new Error("The server returned a repeated teammate page.");
      }
      return page;
    },
    getNextPageParam: (page, pages) =>
      page.has_more
        ? {
            cursor: page.next_cursor,
            userIds: pages.flatMap((previous) =>
              previous.items.map((item) => item.user_id),
            ),
            cursors: pages.flatMap((previous) =>
              previous.next_cursor ? [previous.next_cursor] : [],
            ),
          }
        : undefined,
    gcTime: 0,
    staleTime: Infinity,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const participants = new Map(
    directory.data?.pages.flatMap((page) =>
      page.items.map((item) => [item.user_id, item] as const),
    ),
  );
  const selected = new Map(
    directory.data?.pages
      .at(-1)
      ?.selected_items.map((item) => [item.user_id, item] as const),
  );
  const directoryRevisionMatches =
    directory.data?.pages.every(
      (page) => page.plan_revision === record.revision,
    ) ?? false;
  const eligibilityConfirmed =
    directoryRevisionMatches && !directory.isError && !directory.isFetching;
  for (const item of selected.values()) participants.set(item.user_id, item);
  // Only the same saved revision can confirm an off-page participant is unavailable.
  for (const id of [
    record.plan?.assignee_user_id,
    record.plan?.verifier_user_id,
  ])
    if (id && eligibilityConfirmed && !selected.has(id))
      participants.delete(id);
  const active = useRef(true);
  const write = useRef<AbortController | null>(null);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      write.current?.abort();
    };
  }, []);

  function edit(change: Partial<WorkPlan>) {
    setPlan((current) => ({ ...current, ...change }));
    setSaved(false);
  }
  async function save() {
    setError("");
    setSaved(false);
    try {
      validateWorkPlan(plan, props.requestId);
    } catch (failure) {
      setError((failure as Error).message);
      return;
    }
    setPending(true);
    const controller = new AbortController();
    write.current = controller;
    try {
      const result = await putWorkPlan({
        workspace: props.workspace,
        requestId: props.requestId,
        expectedRevision: record.revision,
        plan,
        signal: controller.signal,
      });
      if (!active.current) return;
      setRecord(result);
      setPlan(result.plan!);
      setSaved(true);
      void queryClient.invalidateQueries({
        queryKey: [
          "portal",
          props.userId,
          props.workspace,
          "context",
          props.clientId,
        ],
      });
    } catch (failure) {
      if (active.current) setError((failure as Error).message);
    } finally {
      if (active.current) setPending(false);
    }
  }
  async function reloadPlan() {
    setPending(true);
    setError("");
    setSaved(false);
    try {
      const result = await reload();
      if (active.current && result) {
        setRecord(result);
        setPlan(result.plan ?? emptyPlan);
      }
    } catch (failure) {
      if (active.current) setError((failure as Error).message);
    } finally {
      if (active.current) setPending(false);
    }
  }
  const candidates = new Map(
    props.requests
      .filter((item) => item.id !== props.requestId)
      .map((item) => [item.id, item.subject]),
  );
  for (const id of plan.dependency_thread_ids)
    if (!candidates.has(id))
      candidates.set(id, "Saved dependency outside recent requests");

  return (
    <form
      className="min-w-0 space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!pending) void save();
      }}
    >
      <p className="text-muted-foreground text-sm">
        {record.plan
          ? `Recorded revision ${record.revision}`
          : "No recorded plan yet."}
      </p>
      <fieldset disabled={pending} className="min-w-0 space-y-4">
        <label className="block space-y-1">
          <span>Outcome</span>
          <Textarea
            className="min-h-24 text-base"
            value={plan.outcome}
            onChange={(event) => edit({ outcome: event.target.value })}
          />
        </label>
        <div className="grid min-w-0 gap-4 lg:grid-cols-2">
          {(
            [
              ["Owner", "assignee_user_id"],
              ["Verifier", "verifier_user_id"],
            ] as const
          ).map(([label, field]) => (
            <label key={field} className="block min-w-0 space-y-1">
              <span>{label}</span>
              <select
                className={control}
                value={plan[field] ?? ""}
                onChange={(event) =>
                  edit({ [field]: event.target.value || null })
                }
              >
                <option value="">Unassigned</option>
                {[...participants.values()].map((item) => (
                  <option key={item.user_id} value={item.user_id}>
                    {item.email} ·{" "}
                    {item.role === "account_manager"
                      ? "Account manager"
                      : item.role === "admin"
                        ? "Admin"
                        : "Owner"}
                    {item.user_id === props.userId ? " (you)" : ""}
                  </option>
                ))}
                {plan[field] && !participants.has(plan[field]) && (
                  <option value={plan[field]} disabled>
                    {record.plan?.[field] === plan[field]
                      ? "Saved"
                      : "Selected"}{" "}
                    {label.toLowerCase()} —{" "}
                    {eligibilityConfirmed
                      ? "unavailable; clear or replace"
                      : "eligibility not checked"}
                  </option>
                )}
              </select>
            </label>
          ))}
        </div>
        <p className="text-muted-foreground text-sm">
          Only currently eligible teammates for this client are listed. Saving
          rechecks eligibility. Unavailable selections can be cleared or
          replaced.
        </p>
        {directory.isFetching && (
          <p role="status">Loading eligible teammates…</p>
        )}
        {(directory.error ?? (directory.data && !directoryRevisionMatches)) && (
          <div className="space-y-2">
            <p role="alert">
              {directory.error?.message ??
                "The teammate snapshot does not match the loaded plan revision."}{" "}
              Your selections and edits are retained; eligibility could not be
              checked.
            </p>
            <Button
              type="button"
              variant="outline"
              className="min-h-11"
              disabled={directory.isFetching}
              onClick={() =>
                void (directory.isFetchNextPageError
                  ? directory.fetchNextPage()
                  : directory.refetch())
              }
            >
              Retry teammates
            </Button>
          </div>
        )}
        {directory.hasNextPage &&
          !directory.error &&
          directoryRevisionMatches && (
            <Button
              type="button"
              variant="outline"
              className="min-h-11"
              disabled={directory.isFetching}
              onClick={() => void directory.fetchNextPage()}
            >
              Load more teammates
            </Button>
          )}
        <label className="block min-w-0 space-y-1">
          <span>Due date</span>
          <Input
            className="min-h-11 min-w-0 text-base"
            aria-label="Due date"
            type="datetime-local"
            step="1"
            value={
              plan.due_at
                ? format(new Date(plan.due_at), "yyyy-MM-dd'T'HH:mm:ss")
                : ""
            }
            onChange={(event) =>
              edit({
                due_at: event.target.value
                  ? new Date(event.target.value).toISOString()
                  : null,
              })
            }
          />
          <span className="text-muted-foreground block text-sm">
            Optional, in your local time zone.
          </span>
        </label>
        <fieldset className="min-w-0 space-y-1">
          <legend>Dependencies</legend>
          <p className="text-muted-foreground text-sm">
            Choose up to 10 requests for this client.
          </p>
          {props.requestsLoading && (
            <p role="status">Loading recent requests…</p>
          )}
          {props.requestsError && (
            <p>Recent requests unavailable: {props.requestsError}</p>
          )}
          {[...candidates].map(([id, subject]) => (
            <label key={id} className="flex min-h-11 items-center gap-2">
              <input
                type="checkbox"
                checked={plan.dependency_thread_ids.includes(id)}
                disabled={
                  !plan.dependency_thread_ids.includes(id) &&
                  plan.dependency_thread_ids.length >= 10
                }
                onChange={(event) =>
                  edit({
                    dependency_thread_ids: event.target.checked
                      ? [...plan.dependency_thread_ids, id]
                      : plan.dependency_thread_ids.filter(
                          (value) => value !== id,
                        ),
                  })
                }
              />
              <span>{subject}</span>
            </label>
          ))}
          {!candidates.size &&
            !props.requestsLoading &&
            !props.requestsError && (
              <p className="text-muted-foreground text-sm">
                No other recent requests available.
              </p>
            )}
          {props.hasMoreRequests && (
            <p className="text-muted-foreground text-sm">
              Only recent requests are shown. Saved dependencies outside this
              list are retained.
            </p>
          )}
        </fieldset>
        <label className="block space-y-1">
          <span>Status</span>
          <select
            className={control}
            value={plan.status}
            onChange={(event) =>
              edit({ status: event.target.value as WorkPlan["status"] })
            }
          >
            <option value="planned">Planned</option>
            <option value="in_progress">In progress</option>
            <option value="blocked">Blocked</option>
            <option value="reported_complete">
              Reported complete (unverified)
            </option>
          </select>
        </label>
        <label className="block space-y-1">
          <span>Next action</span>
          <Textarea
            className="min-h-24 text-base"
            value={plan.next_action}
            onChange={(event) => edit({ next_action: event.target.value })}
          />
        </label>
        <fieldset className="min-w-0 space-y-3">
          <legend>Evidence references</legend>
          <p className="text-muted-foreground text-sm">
            Staff-recorded references are unverified. Links are not opened or
            checked automatically.
          </p>
          {plan.evidence_refs.map((reference, index) => (
            <div key={index} className="min-w-0 space-y-2 rounded border p-3">
              <label className="block space-y-1">
                <span>Evidence kind {index + 1}</span>
                <select
                  className={control}
                  value={reference.kind}
                  onChange={(event) =>
                    edit({
                      evidence_refs: plan.evidence_refs.map((item, position) =>
                        position === index
                          ? {
                              ...item,
                              kind: event.target.value as "source" | "delivery",
                            }
                          : item,
                      ),
                    })
                  }
                >
                  <option value="source">Source</option>
                  <option value="delivery">Delivery</option>
                </select>
              </label>
              <label className="block space-y-1">
                <span>Evidence reference {index + 1}</span>
                <Input
                  className="min-h-11 text-base"
                  value={reference.reference}
                  onChange={(event) =>
                    edit({
                      evidence_refs: plan.evidence_refs.map((item, position) =>
                        position === index
                          ? { ...item, reference: event.target.value }
                          : item,
                      ),
                    })
                  }
                />
              </label>
              <Button
                type="button"
                variant="outline"
                className="min-h-11"
                aria-label={`Remove evidence reference ${index + 1}`}
                onClick={() =>
                  edit({
                    evidence_refs: plan.evidence_refs.filter(
                      (_, position) => position !== index,
                    ),
                  })
                }
              >
                Remove reference
              </Button>
            </div>
          ))}
          <Button
            type="button"
            variant="outline"
            className="min-h-11"
            disabled={plan.evidence_refs.length >= 10}
            onClick={() =>
              edit({
                evidence_refs: [
                  ...plan.evidence_refs,
                  { kind: "source", reference: "" },
                ],
              })
            }
          >
            Add evidence reference
          </Button>
        </fieldset>
      </fieldset>
      {error && (
        <p role="alert">
          {error} Your edits are retained. Reload the stored plan before
          resolving a conflict; saving is never retried automatically.
        </p>
      )}
      {saved && (
        <p role="status">
          Saved work plan revision {record.revision}. Staff recorded,
          unverified.
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" className="min-h-11" disabled={pending}>
          {pending ? "Working…" : "Save work plan"}
        </Button>
        <Button
          type="button"
          variant="outline"
          className="min-h-11"
          disabled={pending}
          onClick={() => void reloadPlan()}
        >
          Reload plan
        </Button>
      </div>
      <p className="text-muted-foreground text-sm">
        Reload replaces unsaved edits with the latest stored plan.
      </p>
    </form>
  );
}
