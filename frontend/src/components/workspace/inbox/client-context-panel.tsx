import Link from "next/link";

type RequestSummary = {
  id: string;
  subject: string;
  status: string;
  portal_state: string;
  updated_at: string | null;
};

export type ClientContext = {
  schema: "client_operating_context.v1";
  workspace_id: string;
  client: {
    id: string;
    name: string;
    source: { updated_at: string | null };
  };
  requests: { items: RequestSummary[]; has_more: boolean };
  current_request:
    | (RequestSummary & {
        timeline: {
          id: string;
          author_kind: string;
          visibility: string;
          created_at: string | null;
          body: string;
          body_truncated: boolean;
          attachments: { name: string; sha256: string; delivery: string }[];
        }[];
        timeline_truncated: boolean;
        current_draft: { revision: number };
      })
    | null;
  domains: Record<string, { status: string; scope?: string; reason?: string }>;
  freshness: string;
  limits: { requests: number; messages: number };
};

const DOMAIN_NAMES: Record<string, string> = {
  client_identity: "Client identity",
  request_history: "Request history",
  goals: "Goals",
  crm: "CRM",
  campaign_performance: "Campaign performance",
  meetings: "Meetings",
  delivery_priorities: "Delivery priorities",
};

export function ClientContextPanel({
  data,
  loading,
  error,
  onSelect,
  busy,
  workChatId,
  workRunId,
  approvalId,
}: {
  data?: ClientContext;
  loading: boolean;
  error: Error | null;
  onSelect: (id: string) => void;
  busy: boolean;
  workChatId?: string;
  workRunId?: string;
  approvalId?: string;
}) {
  return (
    <section
      aria-label="Client context"
      className="min-w-0 space-y-4 rounded border p-4 [overflow-wrap:anywhere]"
    >
      <h2 className="text-xl font-semibold">Client context</h2>
      {error ? (
        <p role="alert">{error.message}</p>
      ) : !data ? (
        <p role="status">
          {loading
            ? "Loading client context…"
            : "Select a client or request to load context."}
        </p>
      ) : (
        <>
          <div>
            <h3 className="text-lg font-medium">{data.client.name}</h3>
            <p className="text-muted-foreground text-sm">
              Roster updated: {data.client.source.updated_at ?? "Unavailable"}
            </p>
            <p className="text-muted-foreground text-sm">{data.freshness}</p>
          </div>
          <dl className="divide-y text-sm">
            {Object.entries(data.domains).map(([name, domain]) => (
              <div
                key={name}
                className="grid gap-1 py-2 sm:grid-cols-[10rem_1fr]"
              >
                <dt className="font-medium">{DOMAIN_NAMES[name] ?? name}</dt>
                <dd>
                  <span className="font-semibold">
                    {domain.status === "available"
                      ? "Available"
                      : "Unavailable"}
                  </span>
                  <p className="text-muted-foreground">
                    {domain.scope ?? domain.reason}
                  </p>
                </dd>
              </div>
            ))}
          </dl>
          <div>
            <h3 className="font-medium">Recent client requests</h3>
            <p className="text-muted-foreground text-sm">
              Up to {data.limits.requests} stored requests in this workspace.{" "}
              {data.requests.has_more &&
                "More requests are available in Board."}
            </p>
            {!data.requests.items.length && (
              <p className="text-muted-foreground text-sm">
                No stored requests for this client.
              </p>
            )}
            <ul className="divide-y">
              {data.requests.items.map((request) => (
                <li key={request.id}>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => onSelect(request.id)}
                    className="hover:bg-muted min-h-11 w-full py-2 text-left"
                  >
                    <span className="block font-medium">{request.subject}</span>
                    <span className="text-muted-foreground text-sm">
                      {request.portal_state.replaceAll("_", " ")} ·{" "}
                      {request.updated_at ?? "Date unavailable"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          {data.current_request && (
            <details className="rounded border p-3">
              <summary className="min-h-11 cursor-pointer font-medium">
                Request timeline
              </summary>
              <p className="text-muted-foreground text-sm">
                Stored request history · Draft revision{" "}
                {data.current_request.current_draft.revision}
              </p>
              {data.current_request.timeline_truncated && (
                <p className="text-muted-foreground text-sm">
                  History is shortened. The original and newest messages are
                  retained.
                </p>
              )}
              <ol className="mt-3 space-y-3">
                {data.current_request.timeline.map((message) => (
                  <li key={message.id} className="bg-muted/40 rounded p-3">
                    <p className="text-muted-foreground text-sm">
                      {message.author_kind} · {message.visibility} ·{" "}
                      {message.created_at ?? "Date unavailable"}
                    </p>
                    <p className="whitespace-pre-wrap">{message.body}</p>
                    {message.body_truncated && (
                      <p className="text-muted-foreground text-sm">
                        Message shortened.
                      </p>
                    )}
                    {message.attachments.map((attachment, index) => (
                      <p key={index} className="text-sm">
                        {attachment.name} · Attachment descriptor only
                      </p>
                    ))}
                  </li>
                ))}
              </ol>
            </details>
          )}
          <nav
            aria-label="Client work"
            className="flex flex-wrap gap-x-4 text-sm"
          >
            {workChatId && (
              <Link
                className="inline-flex min-h-11 items-center underline"
                href={`/workspace/agents/momobot-max/chats/${encodeURIComponent(workChatId)}`}
              >
                Work conversation
              </Link>
            )}
            {workRunId && (
              <Link
                className="inline-flex min-h-11 items-center underline"
                href="/workspace/command-center"
              >
                Run history
              </Link>
            )}
            {approvalId && (
              <Link
                className="inline-flex min-h-11 items-center underline"
                href="/workspace/approvals"
              >
                Approvals
              </Link>
            )}
            <Link
              className="inline-flex min-h-11 items-center underline"
              href="/workspace/board"
            >
              Board
            </Link>
          </nav>
          {workRunId && (
            <p className="text-muted-foreground text-xs">
              Work run: {workRunId}
            </p>
          )}
        </>
      )}
    </section>
  );
}
