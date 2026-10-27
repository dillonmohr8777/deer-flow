"use client";

import { useEffect, useRef, useState } from "react";

import { fetch as apiFetch } from "@/core/api/fetcher";
import { useAuth } from "@/core/auth/AuthProvider";
import { isClientUser } from "@/core/auth/roles";
import { connectChannelProvider } from "@/core/channels/api";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import {
  sameToolkit,
  useToolkitStatus,
  type ToolkitStatus,
} from "@/core/integrations/composio";
import { useLocalSettings } from "@/core/settings";
import { isStaticWebsiteOnly } from "@/core/static-mode";
import { useWorkspaceSelection } from "@/core/workspaces/hooks";
import { cn } from "@/lib/utils";

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../ui/dialog";

import { ConnectButton } from "./connections/connect-cards";
import { ExperienceModeChooser } from "./experience-mode-chooser";

type ToolState = {
  id: string;
  label: string;
  status: "connected" | "shared" | "requested" | "skipped" | "pending";
  available: boolean;
};
type CatalogEntry = {
  id: string;
  label: string;
  group: string;
  pinned: boolean;
};
export type OnboardingState = {
  required: boolean;
  profile_saved: boolean;
  tools_saved: boolean;
  role: string;
  team: string;
  profile_found: boolean;
  clients: string[];
  tools: string[];
  other: string;
  catalog: CatalogEntry[];
  connections: ToolState[];
};

/*
 * First sign-in for Momentum staff: confirm role and team, pick the tools used
 * every day, connect each one, then land in Easy mode. Steps 1 and 2 cannot be
 * dismissed; step 3 allows a per-tool skip, which the server records. Clients
 * and accounts that already finished keep the old skippable chooser.
 */
export function FirstLoginGate() {
  const { t } = useI18n();
  const { user } = useAuth();
  const [result, setResult] = useState<{
    userId: string;
    state?: OnboardingState;
    failed?: boolean;
  } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [retrying, setRetrying] = useState(false);
  const userId =
    !isStaticWebsiteOnly() && user?.id !== "default" ? user?.id : undefined;
  const staff = !!user && !isClientUser(user);

  useEffect(() => {
    if (!userId || !staff) return;
    const controller = new AbortController();
    onboardingRequest(userId, "", "GET", undefined, controller.signal)
      .then((state) => {
        if (!controller.signal.aborted) setResult({ userId, state });
      })
      .catch(() => {
        if (!controller.signal.aborted) setResult({ userId, failed: true });
      })
      .finally(() => {
        if (!controller.signal.aborted) setRetrying(false);
      });
    return () => controller.abort();
  }, [userId, staff, attempt]);

  if (!staff) return <ExperienceModeChooser key={user?.id} />;
  if (!userId) return null;
  if (result?.userId !== userId || result.failed) {
    const failed = result?.userId === userId && result.failed;
    return (
      <Dialog open onOpenChange={() => undefined}>
        <DialogContent
          showCloseButton={false}
          aria-describedby={undefined}
          onEscapeKeyDown={(event) => event.preventDefault()}
          onPointerDownOutside={(event) => event.preventDefault()}
          onInteractOutside={(event) => event.preventDefault()}
        >
          <DialogHeader>
            <DialogTitle>
              {failed ? t.login.serviceUnavailableTitle : t.common.loading}
            </DialogTitle>
          </DialogHeader>
          {failed && (
            <>
              <p role="alert">{t.settings.models.failed}</p>
              <button
                type="button"
                disabled={retrying}
                onClick={() => {
                  setRetrying(true);
                  setAttempt((current) => current + 1);
                }}
                className="bg-primary text-primary-foreground min-h-11 rounded-md font-semibold disabled:opacity-60"
              >
                {t.common.tryAgain}
              </button>
            </>
          )}
        </DialogContent>
      </Dialog>
    );
  }
  if (result.state?.required) {
    return (
      <OnboardingFlow key={userId} userId={userId} initial={result.state} />
    );
  }
  return <ExperienceModeChooser key={userId} />;
}

async function onboardingRequest(
  userId: string,
  path: string,
  method: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<OnboardingState> {
  const response = await apiFetch(
    `${getBackendBaseURL()}/api/v1/auth/onboarding${path}`,
    {
      method,
      cache: "no-store",
      headers: {
        "X-Expected-User-Id": userId,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: signal
        ? AbortSignal.any([signal, AbortSignal.timeout(15000)])
        : AbortSignal.timeout(15000),
    },
  );
  if (!response.ok) {
    const detail = (await response.json().catch(() => null)) as {
      detail?: unknown;
    } | null;
    throw new Error(
      typeof detail?.detail === "string" && detail.detail
        ? detail.detail
        : response.statusText || `Request failed (${response.status})`,
    );
  }
  const state = (await response.json()) as OnboardingState | null;
  if (typeof state?.required !== "boolean") {
    throw new Error("Invalid onboarding response");
  }
  return state;
}

export function OnboardingFlow({
  userId,
  initial,
}: {
  userId: string;
  initial: OnboardingState;
}) {
  const { t } = useI18n();
  const copy = t.onboarding;
  const [, setSettings] = useLocalSettings();
  const [open, setOpen] = useState(true);
  // Resume where the server says this person left off.
  const [step, setStep] = useState<1 | 2 | 3>(
    initial.tools_saved ? 3 : initial.profile_saved ? 2 : 1,
  );
  const [state, setState] = useState(initial);
  const [role, setRole] = useState(initial.role);
  const [team, setTeam] = useState(initial.team);
  const [tools, setTools] = useState<string[]>(initial.tools);
  const [other, setOther] = useState(initial.other);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [slackCode, setSlackCode] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const workspace = useWorkspaceSelection();
  const request = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    request.current = controller;
    return () => {
      controller.abort();
      if (request.current === controller) request.current = null;
    };
  }, [userId]);
  // Per-person connections, when this server offers them (null otherwise).
  const { data: toolkits } = useToolkitStatus();
  const toolkitFor = (id: string): ToolkitStatus | undefined =>
    toolkits?.find((row) => sameToolkit(row.toolkit, id));
  const needle = query.trim().toLowerCase();
  // Pinned common tools stay first; the rest of the catalog is grouped.
  const groups = new Map<string, CatalogEntry[]>();
  for (const entry of initial.catalog) {
    if (needle && !entry.label.toLowerCase().includes(needle)) continue;
    const group = entry.pinned ? copy.pinnedGroup : entry.group;
    groups.set(group, [...(groups.get(group) ?? []), entry]);
  }

  const run = async (action: (signal: AbortSignal) => Promise<void>) => {
    const controller = request.current;
    if (!controller || controller.signal.aborted) return;
    setBusy(true);
    setError(null);
    try {
      await action(controller.signal);
    } catch (err) {
      if (!controller.signal.aborted)
        setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  };

  const saveProfile = () =>
    run(async (signal) => {
      const next = await onboardingRequest(
        userId,
        "/profile",
        "PUT",
        { role, team },
        signal,
      );
      if (signal.aborted) return;
      setState(next);
      setStep(2);
    });
  const saveTools = () =>
    run(async (signal) => {
      const next = await onboardingRequest(
        userId,
        "/tools",
        "PUT",
        { tools, other },
        signal,
      );
      if (signal.aborted) return;
      setState(next);
      setStep(3);
    });
  const record = (tool: string, status: "requested" | "skipped") =>
    run(async (signal) => {
      const next = await onboardingRequest(
        userId,
        `/connections/${tool}`,
        "POST",
        {
          status,
        },
        signal,
      );
      if (!signal.aborted) setState(next);
    });
  const linkSlack = () =>
    run(async (signal) => {
      if (!workspace.data) throw new Error(t.channels.unavailable);
      if (workspace.data.active_workspace_id) {
        await workspace.selectWorkspace(null);
        return;
      }
      // Existing binding-code flow: DM the code to MomoBot in Slack.
      const result = await connectChannelProvider("slack");
      if (!signal.aborted) setSlackCode(result.instruction || result.code);
    });
  const finish = () =>
    run(async (signal) => {
      const next = await onboardingRequest(
        userId,
        "/complete",
        "POST",
        undefined,
        signal,
      );
      if (signal.aborted) return;
      if (next.required) throw new Error(t.settings.models.failed);
      // Easy mode on its matching fast chat mode (MODE_FOR_EXPERIENCE.easy).
      setSettings("context", { experience_mode: "easy", mode: "flash" });
      setOpen(false);
    });

  const toggle = (id: string) =>
    setTools((current) =>
      current.includes(id)
        ? current.filter((tool) => tool !== id)
        : [...current, id],
    );

  return (
    <Dialog open={open} onOpenChange={() => undefined}>
      <DialogContent
        data-treatment="paper"
        className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg"
        showCloseButton={false}
        aria-describedby={undefined}
        onEscapeKeyDown={(event) => event.preventDefault()}
        onPointerDownOutside={(event) => event.preventDefault()}
        onInteractOutside={(event) => event.preventDefault()}
      >
        <DialogHeader className="items-center gap-2 text-center">
          <img
            src="/momentum/momos/lead.svg"
            alt=""
            aria-hidden="true"
            width={48}
            height={48}
            className="size-12"
          />
          <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
            {copy.stepOf.replace("{step}", String(step))}
          </p>
          <DialogTitle className="font-[family-name:var(--m-font-serif)] text-2xl font-normal">
            {step === 1
              ? copy.roleTitle
              : step === 2
                ? copy.toolsTitle
                : copy.connectTitle}
          </DialogTitle>
        </DialogHeader>

        {step === 1 && (
          <form
            className="grid gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              void saveProfile();
            }}
          >
            {initial.profile_found && (
              <p className="text-muted-foreground text-sm">{copy.prefilled}</p>
            )}
            <label className="grid gap-1 text-sm">
              {copy.roleLabel}
              <input
                required
                maxLength={120}
                value={role}
                onChange={(event) => setRole(event.target.value)}
                className="min-h-11 rounded-md border px-3"
              />
            </label>
            <label className="grid gap-1 text-sm">
              {copy.teamLabel}
              <input
                required
                maxLength={120}
                value={team}
                onChange={(event) => setTeam(event.target.value)}
                className="min-h-11 rounded-md border px-3"
              />
            </label>
            {initial.clients.length > 0 && (
              <p className="text-muted-foreground text-sm">
                {copy.clients} {initial.clients.join(", ")}
              </p>
            )}
            <button
              type="submit"
              disabled={busy || !role.trim() || !team.trim()}
              className="bg-primary text-primary-foreground min-h-11 rounded-md font-semibold disabled:opacity-60"
            >
              {copy.continue}
            </button>
          </form>
        )}

        {step === 2 && (
          <form
            className="grid gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              void saveTools();
            }}
          >
            <p className="text-muted-foreground text-sm">{copy.toolsHint}</p>
            <input
              type="search"
              aria-label={copy.searchLabel}
              placeholder={copy.searchLabel}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="min-h-11 rounded-md border px-3"
            />
            <div className="grid max-h-[45vh] gap-3 overflow-y-auto">
              {[...groups].map(([group, entries]) => (
                <fieldset key={group} className="grid gap-2">
                  <legend className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">
                    {group}
                  </legend>
                  <div className="grid grid-cols-2 gap-2">
                    {entries.map((entry) => (
                      <label
                        key={entry.id}
                        className={cn(
                          "flex min-h-11 items-center gap-2 rounded-md border px-3 text-sm",
                          tools.includes(entry.id) && "border-primary",
                        )}
                      >
                        <input
                          type="checkbox"
                          checked={tools.includes(entry.id)}
                          onChange={() => toggle(entry.id)}
                        />
                        {entry.label}
                      </label>
                    ))}
                  </div>
                </fieldset>
              ))}
              {groups.size === 0 && (
                <p className="text-muted-foreground text-sm">{copy.noMatch}</p>
              )}
            </div>
            <label className="grid gap-1 text-sm">
              {copy.otherLabel}
              <input
                maxLength={300}
                value={other}
                onChange={(event) => setOther(event.target.value)}
                className="min-h-11 rounded-md border px-3"
              />
            </label>
            <button
              type="submit"
              disabled={busy || (tools.length === 0 && !other.trim())}
              className="bg-primary text-primary-foreground min-h-11 rounded-md font-semibold disabled:opacity-60"
            >
              {copy.continue}
            </button>
          </form>
        )}

        {step === 3 && (
          <div className="grid gap-3">
            <p className="text-muted-foreground text-sm">{copy.connectHint}</p>
            <ul className="grid gap-2">
              {state.connections.map((tool) => {
                const own = toolkitFor(tool.id);
                return (
                  <li
                    key={tool.id}
                    className="flex min-h-11 flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm"
                  >
                    <span className="font-medium">{tool.label}</span>
                    <span className="flex flex-wrap items-center gap-2">
                      {tool.status === "connected" ||
                      tool.status === "shared" ||
                      own?.connected ? (
                        <span>
                          {tool.status === "shared"
                            ? copy.shared
                            : copy.connected}
                        </span>
                      ) : (
                        <>
                          {own?.connectable ? (
                            <ConnectButton toolkit={own.toolkit} />
                          ) : (
                            <>
                              {!tool.available && (
                                <span className="text-muted-foreground text-xs">
                                  {copy.comingSoon}
                                </span>
                              )}
                              {tool.id === "slack" && (
                                <button
                                  type="button"
                                  disabled={
                                    busy ||
                                    workspace.busy ||
                                    workspace.isLoading
                                  }
                                  onClick={() => void linkSlack()}
                                  className="min-h-11 rounded-md border px-2"
                                >
                                  {copy.linkSlack}
                                </button>
                              )}
                              {tool.status === "requested" ? (
                                <span>{copy.requested}</span>
                              ) : (
                                <button
                                  type="button"
                                  disabled={busy}
                                  onClick={() =>
                                    void record(tool.id, "requested")
                                  }
                                  className="min-h-11 rounded-md border px-2"
                                >
                                  {copy.request}
                                </button>
                              )}
                            </>
                          )}
                          {tool.status === "skipped" ? (
                            <span className="text-muted-foreground">
                              {copy.skipped}
                            </span>
                          ) : (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void record(tool.id, "skipped")}
                              className="text-muted-foreground min-h-11 px-2 underline-offset-4 hover:underline"
                            >
                              {copy.skip}
                            </button>
                          )}
                        </>
                      )}
                    </span>
                  </li>
                );
              })}
            </ul>
            {slackCode && (
              <p role="status" className="rounded-md border p-3 text-sm">
                {slackCode}
              </p>
            )}
            <button
              type="button"
              disabled={busy}
              onClick={() => void finish()}
              className="bg-primary text-primary-foreground min-h-11 rounded-md font-semibold disabled:opacity-60"
            >
              {copy.finish}
            </button>
          </div>
        )}

        {error && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}
