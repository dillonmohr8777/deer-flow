"use client";

import { CheckIcon, CopyIcon, TriangleAlertIcon } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { UnauthorizedError } from "@/core/api/errors";
import { writeTextToClipboard } from "@/core/clipboard";
import { useI18n } from "@/core/i18n/hooks";
import {
  buildInviteLink,
  createInvitation,
  defaultInviteWorkspaceId,
  INVITE_ROLES,
  type InviteFailureKind,
  InviteRequestError,
  type InviteRole,
  inviteTargets,
  loadInviteWorkspaces,
  type WorkspaceOption,
} from "@/core/invitations/api";
import { cn } from "@/lib/utils";

import { SettingsSection } from "./settings-section";

type WorkspaceState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; targets: WorkspaceOption[]; defaultId: string };

type Created = { link: string; email: string; expiresAt: string };

const CONTROL_CLASS =
  "border-input bg-background focus-visible:border-ring focus-visible:ring-ring/50 h-11 w-full min-w-0 rounded-md border px-3 text-base shadow-xs outline-none focus-visible:ring-[3px] md:text-sm";

function formatExpiry(iso: string): string {
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? iso : parsed.toLocaleString();
}

export function InviteSettingsPage() {
  const { t } = useI18n();
  const text = t.settings.invite;
  const ids = {
    email: useId(),
    emailError: useId(),
    role: useId(),
    roleHelp: useId(),
    org: useId(),
    link: useId(),
  };
  const linkInputRef = useRef<HTMLInputElement>(null);

  const [workspaces, setWorkspaces] = useState<WorkspaceState>({
    status: "loading",
  });
  const [reloadKey, setReloadKey] = useState(0);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<InviteRole>("member");
  const [orgId, setOrgId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [failure, setFailure] = useState<InviteFailureKind | null>(null);
  const [created, setCreated] = useState<Created | null>(null);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">(
    "idle",
  );

  useEffect(() => {
    const controller = new AbortController();
    setWorkspaces({ status: "loading" });
    loadInviteWorkspaces(controller.signal)
      .then((result) => {
        const targets = inviteTargets(result.workspaces);
        const defaultId = defaultInviteWorkspaceId(
          targets,
          result.active_workspace_id,
        );
        setOrgId(defaultId);
        setWorkspaces({ status: "ready", targets, defaultId });
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted || cause instanceof UnauthorizedError) {
          return;
        }
        setWorkspaces({ status: "error" });
      });
    return () => controller.abort();
  }, [reloadKey]);

  useEffect(() => {
    if (created) linkInputRef.current?.focus();
  }, [created]);

  const submit = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const trimmed = email.trim();
      if (!orgId || submitting) return;
      if (!trimmed) {
        setFailure("invalid_email");
        return;
      }
      setSubmitting(true);
      setFailure(null);
      try {
        const invitation = await createInvitation({
          organizationId: orgId,
          email: trimmed,
          role,
        });
        setCopyState("idle");
        setCreated({
          link: buildInviteLink(window.location.origin, invitation.token),
          email: invitation.email,
          expiresAt: invitation.expires_at,
        });
      } catch (cause) {
        if (cause instanceof UnauthorizedError) return;
        setFailure(
          cause instanceof InviteRequestError ? cause.kind : "unknown",
        );
      } finally {
        setSubmitting(false);
      }
    },
    [email, orgId, role, submitting],
  );

  async function copyLink() {
    if (!created) return;
    const ok = await writeTextToClipboard(created.link);
    setCopyState(ok ? "copied" : "failed");
  }

  function reset() {
    setCreated(null);
    setEmail("");
    setFailure(null);
    setCopyState("idle");
  }

  const errorMessages: Record<InviteFailureKind, string> = {
    frozen: text.errors.frozen,
    forbidden: text.errors.forbidden,
    conflict: text.errors.conflict,
    invalid_email: text.errors.invalidEmail,
    invalid: text.errors.invalid,
    unavailable: text.errors.unavailable,
    network: text.errors.network,
    unknown: text.errors.unknown,
  };

  let body: React.ReactNode;
  if (workspaces.status === "loading") {
    body = (
      <p role="status" className="text-muted-foreground text-sm">
        {text.loading}
      </p>
    );
  } else if (workspaces.status === "error") {
    body = (
      <div className="space-y-3">
        <p role="alert" className="text-destructive text-sm">
          {text.loadFailed}
        </p>
        <Button
          type="button"
          variant="outline"
          className="h-11"
          onClick={() => setReloadKey((key) => key + 1)}
        >
          {text.retry}
        </Button>
      </div>
    );
  } else if (workspaces.targets.length === 0) {
    body = <p className="text-muted-foreground text-sm">{text.notAllowed}</p>;
  } else if (created) {
    body = (
      <div className="space-y-4">
        <p role="status" aria-live="polite" className="text-sm font-medium">
          {text.successTitle(created.email)}
        </p>
        <div className="space-y-2">
          <label htmlFor={ids.link} className="text-sm font-medium">
            {text.linkLabel}
          </label>
          <input
            id={ids.link}
            ref={linkInputRef}
            readOnly
            value={created.link}
            onFocus={(event) => event.currentTarget.select()}
            className={cn(CONTROL_CLASS, "font-mono text-xs md:text-xs")}
          />
          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              className="h-11"
              onClick={() => void copyLink()}
            >
              {copyState === "copied" ? <CheckIcon /> : <CopyIcon />}
              {copyState === "copied" ? text.copied : text.copy}
            </Button>
            <span className="text-muted-foreground text-sm">
              {text.expires(formatExpiry(created.expiresAt))}
            </span>
          </div>
          {copyState === "failed" && (
            <p role="alert" className="text-destructive text-sm">
              {text.copyFailed}
            </p>
          )}
        </div>
        <div className="border-border flex items-start gap-2 rounded-md border p-3 text-sm">
          <TriangleAlertIcon className="mt-0.5 size-4 shrink-0" aria-hidden />
          <p>{text.shownOnce}</p>
        </div>
        <Button
          type="button"
          variant="outline"
          className="h-11"
          onClick={reset}
        >
          {text.inviteAnother}
        </Button>
      </div>
    );
  } else {
    body = (
      <form
        noValidate
        className="space-y-4"
        onSubmit={(event) => void submit(event)}
      >
        <div className="space-y-2">
          <label htmlFor={ids.org} className="text-sm font-medium">
            {text.workspaceLabel}
          </label>
          <select
            id={ids.org}
            className={CONTROL_CLASS}
            value={orgId}
            onChange={(event) => setOrgId(event.target.value)}
          >
            {workspaces.targets.map((workspace) => (
              <option key={workspace.id} value={workspace.id}>
                {workspace.name}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-2">
          <label htmlFor={ids.email} className="text-sm font-medium">
            {text.emailLabel}
          </label>
          <Input
            id={ids.email}
            type="email"
            inputMode="email"
            autoComplete="off"
            className="h-11"
            placeholder={text.emailPlaceholder}
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            aria-invalid={failure === "invalid_email"}
            aria-describedby={
              failure === "invalid_email" ? ids.emailError : undefined
            }
          />
        </div>
        <div className="space-y-2">
          <label htmlFor={ids.role} className="text-sm font-medium">
            {text.roleLabel}
          </label>
          <select
            id={ids.role}
            className={CONTROL_CLASS}
            value={role}
            aria-describedby={ids.roleHelp}
            onChange={(event) => setRole(event.target.value as InviteRole)}
          >
            {INVITE_ROLES.map((value) => (
              <option key={value} value={value}>
                {
                  {
                    member: text.roleMember,
                    admin: text.roleAdmin,
                    client: text.roleClient,
                  }[value]
                }
              </option>
            ))}
          </select>
          <p id={ids.roleHelp} className="text-muted-foreground text-sm">
            {text.roleHelp[role]}
          </p>
        </div>
        {failure && (
          <p
            role="alert"
            id={failure === "invalid_email" ? ids.emailError : undefined}
            className="text-destructive text-sm"
          >
            {errorMessages[failure]}
          </p>
        )}
        <Button type="submit" className="h-11" disabled={submitting}>
          {submitting ? text.submitting : text.submit}
        </Button>
      </form>
    );
  }

  return (
    <SettingsSection title={text.title} description={text.description}>
      {body}
    </SettingsSection>
  );
}
