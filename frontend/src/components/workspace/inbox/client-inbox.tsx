"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { fetch as apiFetch } from "@/core/api/fetcher";
import { useAuth } from "@/core/auth/AuthProvider";
import { getBackendBaseURL } from "@/core/config";
import { isStaticWebsiteOnly } from "@/core/static-mode";

type DraftAttachment = { name: string; content: string };
type Message = {
  id: string;
  author: string;
  body: string;
  created_at: string;
  attachments: { name: string; sha256: string }[];
};
type Conversation = {
  id: string;
  client_id: string;
  subject: string;
  state: string;
  revision: number;
  approval_id?: string;
  publish_receipt: string | null;
  work_chat_id?: string;
  work_run_id?: string;
};
type Detail = Conversation & {
  work_status?: string;
  messages: Message[];
  can_review: boolean;
  can_draft: boolean;
  draft?: {
    body: string;
    attachments: { name: string; content: string }[];
  } | null;
};
type Roster = {
  workspace_id: string;
  clients: { id: string; name: string }[];
  can_review: boolean;
  can_draft: boolean;
};
const STATES = {
  all: "All requests",
  pending: "Pending",
  needs_approval: "Needs approval",
  published: "Published",
};
const STATE_LABELS: Record<string, string> = {
  pending: "Pending",
  running: "Momo is working",
  needs_approval: "Needs approval",
  published: "Published in your portal",
};
const label = (state: string) => STATE_LABELS[state] ?? state;

async function api<T>(
  path: string,
  options: { signal?: AbortSignal; workspace?: string; body?: unknown } = {},
): Promise<T> {
  const response = await apiFetch(
    `${getBackendBaseURL()}/api/client-portal${path}`,
    {
      method: options.body === undefined ? "GET" : "POST",
      signal: options.signal,
      headers: {
        "Content-Type": "application/json",
        ...(options.workspace
          ? { "X-Portal-Workspace": options.workspace }
          : {}),
      },
      body:
        options.body === undefined ? undefined : JSON.stringify(options.body),
      cache: "no-store",
    },
  );
  if (!response.ok) {
    const error = (await response.json().catch(() => ({}))) as {
      detail?: string;
    };
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : "Inbox unavailable. Please retry.",
    );
  }
  return response.json() as Promise<T>;
}

export function ClientInbox() {
  const { user } = useAuth();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [state, setState] = useState("all");
  const [offset, setOffset] = useState(0);
  const [composing, setComposing] = useState(false);
  const [clientId, setClientId] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState<DraftAttachment[]>([]);
  // Preserve the same admission key after an uncertain response; never retry as a new send.
  const submission = useRef<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const enabled = Boolean(user) && !isStaticWebsiteOnly();
  const roster = useQuery({
    queryKey: ["portal-roster", user?.id],
    enabled,
    queryFn: ({ signal }) => api<Roster>("/clients", { signal }),
  });
  const workspace = roster.data?.workspace_id;
  const key = ["portal", user?.id, workspace];
  const list = useQuery({
    queryKey: [...key, "list", query, state, offset],
    enabled: enabled && Boolean(workspace),
    queryFn: ({ signal }) =>
      api<{ threads: Conversation[]; has_more: boolean }>(
        `/threads?q=${encodeURIComponent(query)}&state=${state}&limit=30&offset=${offset}`,
        { signal, workspace },
      ),
  });
  const detail = useQuery({
    queryKey: [...key, "detail", selected],
    enabled: enabled && Boolean(workspace && selected),
    queryFn: ({ signal }) =>
      api<Detail>(`/threads/${selected!}`, { signal, workspace }),
    refetchInterval: (query) =>
      query.state.data?.state === "running" ? 5000 : false,
  });
  const savedDraft = detail.data?.draft;
  const savedBody = savedDraft?.body ?? "";
  const savedAttachments = JSON.stringify(
    savedDraft?.attachments.map(({ name, content }) => ({ name, content })) ??
      [],
  );
  useEffect(() => {
    setDraft(savedBody);
    setAttachments(JSON.parse(savedAttachments) as DraftAttachment[]);
  }, [selected, savedBody, savedAttachments]);
  useEffect(() => {
    setSelected(null);
    setError(null);
    setComposing(false);
  }, [user?.id, workspace]);
  const action = useMutation({
    mutationFn: async ({ path, payload }: { path: string; payload: unknown }) =>
      api<Detail & { href?: string }>(path, { workspace, body: payload }),
    onSuccess: async (result) => {
      setError(null);
      if (result.href) router.push(result.href);
      if (result.id) {
        setSelected(result.id);
        queryClient.setQueryData([...key, "detail", result.id], result);
      }
      await queryClient.invalidateQueries({ queryKey: key });
    },
    onError: (failure) => setError(failure.message),
  });
  const send = async () => {
    submission.current ??= crypto.randomUUID();
    try {
      await action.mutateAsync({
        path: "/threads",
        payload: {
          client_id: clientId || roster.data?.clients[0]?.id,
          submission_key: submission.current,
          subject,
          body,
        },
      });
      submission.current = null;
      setComposing(false);
      setSubject("");
      setBody("");
    } catch {
      /* Preserve all inputs and key for a deliberate retry. */
    }
  };
  const download = async (message: Message, name: string) => {
    if (!workspace || !selected) return;
    const response = await apiFetch(
      `${getBackendBaseURL()}/api/client-portal/threads/${selected}/messages/${message.id}/attachments/${encodeURIComponent(name)}`,
      { headers: { "X-Portal-Workspace": workspace } },
    );
    if (!response.ok) {
      setError("This file is no longer available. Refresh the conversation.");
      return;
    }
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = name;
    anchor.click();
    URL.revokeObjectURL(url);
  };
  const current = detail.data;
  const busy = action.isPending;
  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <main
          className="h-full min-w-0 overflow-y-auto p-4 md:p-6"
          data-testid="client-inbox"
        >
          <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-muted-foreground text-sm">MomoBot1.1</p>
              <h1 className="text-2xl font-semibold">Client inbox</h1>
              <p className="text-muted-foreground text-sm">
                Requests, progress and approved replies in one place.
              </p>
            </div>
            <Button
              onClick={() => {
                setComposing(true);
                setSelected(null);
              }}
              disabled={!roster.data?.clients.length}
            >
              New request
            </Button>
          </header>
          {(Boolean(error) || roster.isError || list.isError) && (
            <p role="alert" className="mb-4 break-words text-red-700">
              {error ?? roster.error?.message ?? list.error?.message}
            </p>
          )}
          <div className="grid min-w-0 gap-5 lg:grid-cols-[minmax(230px,320px)_minmax(0,1fr)]">
            <aside
              className="min-w-0 space-y-3"
              aria-label="Inbox conversations"
            >
              <Input
                aria-label="Search requests"
                placeholder="Search subjects"
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setOffset(0);
                }}
              />
              <select
                aria-label="Request status"
                className="bg-background min-h-11 w-full rounded border p-2"
                value={state}
                onChange={(event) => {
                  setState(event.target.value);
                  setOffset(0);
                }}
              >
                {Object.entries(STATES).map(([value, text]) => (
                  <option key={value} value={value}>
                    {text}
                  </option>
                ))}
              </select>
              {list.isLoading && <p role="status">Loading requests…</p>}
              {list.data?.threads.length === 0 && (
                <p className="text-muted-foreground py-5">
                  No requests here yet.
                </p>
              )}
              <ul className="divide-y rounded border">
                {list.data?.threads.map((thread) => (
                  <li key={thread.id}>
                    <button
                      className="hover:bg-muted min-h-16 w-full p-3 text-left"
                      aria-current={selected === thread.id}
                      onClick={() => {
                        setSelected(thread.id);
                        setComposing(false);
                        setError(null);
                      }}
                    >
                      <span className="block font-medium break-words">
                        {thread.subject}
                      </span>
                      <span className="text-muted-foreground text-sm">
                        {label(thread.state)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
              <div className="flex justify-between gap-2">
                <Button
                  variant="outline"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - 30))}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  disabled={!list.data?.has_more}
                  onClick={() => setOffset(offset + 30)}
                >
                  Next
                </Button>
              </div>
            </aside>
            <section
              className="min-w-0 rounded border p-4"
              aria-label="Conversation"
            >
              {composing ? (
                <form
                  className="space-y-4"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void send();
                  }}
                >
                  <h2 className="text-lg font-medium">
                    What can Momo help with?
                  </h2>
                  <label className="block">
                    Client
                    <select
                      className="bg-background mt-1 min-h-11 w-full rounded border p-2"
                      value={
                        clientId
                          ? clientId
                          : (roster.data?.clients[0]?.id ?? "")
                      }
                      onChange={(event) => setClientId(event.target.value)}
                    >
                      {roster.data?.clients.map((client) => (
                        <option key={client.id} value={client.id}>
                          {client.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block">
                    Subject
                    <Input
                      required
                      maxLength={255}
                      value={subject}
                      onChange={(event) => setSubject(event.target.value)}
                    />
                  </label>
                  <label className="block">
                    Your request
                    <Textarea
                      required
                      maxLength={12000}
                      className="min-h-40 text-base"
                      value={body}
                      onChange={(event) => setBody(event.target.value)}
                    />
                  </label>
                  <Button type="submit" disabled={busy}>
                    {busy ? "Saving…" : "Submit request"}
                  </Button>
                  <p className="text-muted-foreground text-sm">
                    Your request stays in this portal. Your team reviews replies
                    before they appear here.
                  </p>
                </form>
              ) : !selected ? (
                <p className="text-muted-foreground py-8">
                  Choose a conversation or start a new request.
                </p>
              ) : detail.isLoading ? (
                <p role="status">Loading conversation…</p>
              ) : detail.isError ? (
                <p role="alert">{detail.error.message}</p>
              ) : (
                current && (
                  <>
                    <h2 className="text-xl font-semibold break-words">
                      {current.subject}
                    </h2>
                    <p
                      className="text-muted-foreground mb-4 text-sm"
                      role="status"
                    >
                      {label(current.state)}
                    </p>
                    {current.work_status && current.state !== "running" && (
                      <p className="text-muted-foreground mb-3 text-sm">
                        Work status: {current.work_status}. Your team will
                        review the result.
                      </p>
                    )}
                    <div className="mb-5 flex flex-wrap gap-2">
                      {!current.can_draft && (
                        <Button
                          variant="outline"
                          disabled={busy}
                          onClick={() =>
                            action.mutate({
                              path: `/threads/${selected}/chat`,
                              payload: {},
                            })
                          }
                        >
                          Talk to your Momo
                        </Button>
                      )}
                      {current.can_draft && !current.publish_receipt && (
                        <Button
                          variant="outline"
                          disabled={busy}
                          onClick={() =>
                            action.mutate({
                              path: `/threads/${selected}/work`,
                              payload: {},
                            })
                          }
                        >
                          Ask Momo to work
                        </Button>
                      )}
                      {current.can_draft && current.work_chat_id && (
                        <Button
                          variant="outline"
                          onClick={() =>
                            router.push(
                              `/workspace/agents/momobot-max/chats/${current.work_chat_id}`,
                            )
                          }
                        >
                          Open work conversation
                        </Button>
                      )}
                    </div>
                    <ol className="space-y-4">
                      {current.messages.map((message) => (
                        <li
                          key={message.id}
                          className="bg-muted/40 min-w-0 rounded p-3"
                        >
                          <p className="text-sm font-medium">
                            {message.author}
                          </p>
                          <p className="[overflow-wrap:anywhere] break-words whitespace-pre-wrap">
                            {message.body}
                          </p>
                          {message.attachments.map((attachment) => (
                            <Button
                              variant="link"
                              key={attachment.name}
                              className="max-w-full break-all whitespace-normal"
                              onClick={() =>
                                void download(message, attachment.name)
                              }
                            >
                              Download {attachment.name}
                            </Button>
                          ))}
                        </li>
                      ))}
                    </ol>
                    {current.can_draft && !current.publish_receipt && (
                      <div className="mt-6 space-y-3 border-t pt-4">
                        <h3 className="font-medium">Internal reply draft</h3>
                        <p className="text-muted-foreground text-sm">
                          Clients cannot read this draft. Saving a change
                          requires a new approval.
                        </p>
                        <Textarea
                          aria-label="Internal reply draft"
                          className="min-h-40 text-base"
                          value={draft}
                          maxLength={12000}
                          onChange={(event) => setDraft(event.target.value)}
                        />
                        {attachments.map((attachment, index) => (
                          <fieldset
                            key={index}
                            className="min-w-0 space-y-2 rounded border p-3"
                          >
                            <label className="block text-sm">
                              Deliverable filename
                              {index > 0 ? ` ${index + 1}` : ""}
                              <Input
                                value={attachment.name}
                                onChange={(event) =>
                                  setAttachments((items) =>
                                    items.map((item, position) =>
                                      position === index
                                        ? { ...item, name: event.target.value }
                                        : item,
                                    ),
                                  )
                                }
                              />
                            </label>
                            <Textarea
                              aria-label={`Deliverable content${index > 0 ? ` ${index + 1}` : ""}`}
                              placeholder="Report or deliverable text"
                              value={attachment.content}
                              maxLength={16000}
                              onChange={(event) =>
                                setAttachments((items) =>
                                  items.map((item, position) =>
                                    position === index
                                      ? { ...item, content: event.target.value }
                                      : item,
                                  ),
                                )
                              }
                            />
                            <Button
                              variant="outline"
                              aria-label={`Remove deliverable ${index + 1}`}
                              onClick={() =>
                                setAttachments((items) =>
                                  items.filter(
                                    (_, position) => position !== index,
                                  ),
                                )
                              }
                            >
                              Remove deliverable
                            </Button>
                          </fieldset>
                        ))}
                        <Button
                          variant="outline"
                          disabled={busy || attachments.length >= 3}
                          onClick={() =>
                            setAttachments((items) => [
                              ...items,
                              {
                                name:
                                  items.length === 0
                                    ? "report.md"
                                    : `report-${items.length + 1}.md`,
                                content: "",
                              },
                            ])
                          }
                        >
                          Add deliverable
                        </Button>
                        <Button
                          disabled={busy || !draft.trim()}
                          onClick={() =>
                            action.mutate({
                              path: `/threads/${selected}/draft`,
                              payload: {
                                expected_revision: current.revision,
                                body: draft,
                                attachments,
                              },
                            })
                          }
                        >
                          Save draft for review
                        </Button>
                        {current.can_review && current.approval_id && (
                          <Button
                            className="ml-2"
                            disabled={
                              busy ||
                              draft !== current.draft?.body ||
                              JSON.stringify(attachments) !== savedAttachments
                            }
                            onClick={() =>
                              action.mutate({
                                path: `/threads/${selected}/publish`,
                                payload: {
                                  approval_id: current.approval_id,
                                  expected_revision: current.revision,
                                },
                              })
                            }
                          >
                            Approve exact draft and publish
                          </Button>
                        )}
                      </div>
                    )}
                    {current.publish_receipt && (
                      <p className="text-muted-foreground mt-5 text-xs break-all">
                        Published in this portal · Receipt{" "}
                        {current.publish_receipt}
                      </p>
                    )}
                  </>
                )
              )}
            </section>
          </div>
        </main>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
