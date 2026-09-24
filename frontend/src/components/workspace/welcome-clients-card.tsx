"use client";

import { XIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { fetch as apiFetch } from "@/core/api/fetcher";
import { useAuth } from "@/core/auth/AuthProvider";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { useLocalSettings } from "@/core/settings";
import { isStaticWebsiteOnly } from "@/core/static-mode";
import {
  buildComposerDraftKey,
  getSessionComposerDraftStorage,
  writeComposerDraft,
} from "@/core/threads/composer-draft";

/*
 * One-time "Set up my clients" card, shown after the experience-mode chooser
 * resolves (settings.context.experience_mode becomes non-null the moment the
 * person picks a mode or skips it -- see experience-mode-chooser.tsx). Starts
 * a new chat pre-loaded with the welcome skill via the same composer-draft
 * handoff a slash-skill activation already uses, so InputBox's own draft
 * hydration (input-box.tsx) renders it -- no bespoke "first message" wiring.
 * Dismissal mirrors experience-mode-chooser.tsx exactly: a server-side
 * preference (`welcome_clients_dismissed` on the same /api/v1/auth/preferences
 * resource `experience_mode` lives on) for a real account, with the local
 * settings mirror as the read model and the only source of truth for
 * static/anonymous sessions that never reach the server call.
 */
export function WelcomeClientsCard() {
  const { t } = useI18n();
  const router = useRouter();
  const { user } = useAuth();
  const [settings, setSettings] = useLocalSettings();
  const [checkedServer, setCheckedServer] = useState(false);
  const userId =
    !isStaticWebsiteOnly() && user?.id !== "default" ? user?.id : undefined;
  const dismissed = settings.context.welcomeClientsCardDismissed === true;

  useEffect(() => {
    if (!userId || dismissed) {
      setCheckedServer(true);
      return;
    }
    let cancelled = false;
    apiFetch(`${getBackendBaseURL()}/api/v1/auth/preferences`, {
      headers: { "X-Expected-User-Id": userId },
      cache: "no-store",
    })
      .then((response) => (response.ok ? response.json() : null))
      .then((data: { welcome_clients_dismissed?: boolean | null } | null) => {
        if (!cancelled && data?.welcome_clients_dismissed) {
          setSettings("context", { welcomeClientsCardDismissed: true });
        }
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setCheckedServer(true);
      });
    return () => {
      cancelled = true;
    };
    // Runs once per mount/identity; re-checking on every local settings
    // change would re-fetch on the write this effect itself may trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  const dismiss = () => {
    setSettings("context", { welcomeClientsCardDismissed: true });
    if (!userId) return;
    apiFetch(`${getBackendBaseURL()}/api/v1/auth/preferences`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "X-Expected-User-Id": userId,
      },
      body: JSON.stringify({ welcome_clients_dismissed: true }),
    }).catch(() => undefined);
  };

  const start = () => {
    writeComposerDraft(
      getSessionComposerDraftStorage(),
      buildComposerDraftKey({
        userId: user?.id ?? "anonymous",
        agentName: null,
        threadId: "new",
      }),
      { text: "", skillName: "welcome" },
    );
    dismiss();
    router.push("/workspace/chats/new");
  };

  if (
    !settings.context.experience_mode ||
    dismissed ||
    (userId && !checkedServer)
  ) {
    return null;
  }

  return (
    <div
      role="region"
      aria-label={t.workspace.welcomeClientsCardTitle}
      className="bg-muted/60 flex items-center justify-between gap-3 border-b px-4 py-2 text-sm"
    >
      <span className="min-w-0">
        <strong className="font-semibold">
          {t.workspace.welcomeClientsCardTitle}
        </strong>{" "}
        <span className="text-muted-foreground">
          {t.workspace.welcomeClientsCardBody}
        </span>
      </span>
      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          onClick={start}
          className="bg-foreground text-background rounded-md px-3 py-1 text-xs font-medium hover:opacity-90"
        >
          {t.workspace.welcomeClientsCardCta}
        </button>
        <button
          type="button"
          onClick={dismiss}
          aria-label={t.workspace.welcomeClientsCardDismiss}
          className="text-muted-foreground hover:bg-background hover:text-foreground rounded-md border p-1"
        >
          <XIcon className="size-3.5" />
        </button>
      </div>
    </div>
  );
}
