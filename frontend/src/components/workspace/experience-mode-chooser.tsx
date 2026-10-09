"use client";

import { useEffect, useState } from "react";

import { fetch as apiFetch } from "@/core/api/fetcher";
import { useAuth } from "@/core/auth/AuthProvider";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { useLocalSettings } from "@/core/settings";
import { isStaticWebsiteOnly } from "@/core/static-mode";
import { cn } from "@/lib/utils";

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../ui/dialog";

type ExperienceMode = "easy" | "medium" | "hard";

/*
 * First-sign-in chooser: shown once for an account with no saved
 * experience_mode preference. Skippable, defaults to "medium" — which is
 * also what an explicit skip persists, so the chooser never nags twice.
 * Renders as an ordinary Dialog inside the workspace, which defaults to the
 * paper appearance treatment (appearance-preferences.ts), so it picks up
 * the paper "sheet" dialog skin without a bespoke re-implementation.
 */
export function ExperienceModeChooser() {
  const { t } = useI18n();
  const { user } = useAuth();
  const [, setSettings] = useLocalSettings();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState<ExperienceMode | null>(null);
  const userId =
    !isStaticWebsiteOnly() && user?.id !== "default" ? user?.id : undefined;

  useEffect(() => {
    if (!userId) return;
    let cancelled = false;
    apiFetch(`${getBackendBaseURL()}/api/v1/auth/preferences`, {
      headers: { "X-Expected-User-Id": userId },
      cache: "no-store",
    })
      .then((response) => (response.ok ? response.json() : null))
      .then((data: { experience_mode?: ExperienceMode | null } | null) => {
        if (!cancelled && data && data.experience_mode == null) setOpen(true);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [userId]);

  const choose = (mode: ExperienceMode) => {
    if (!userId || saving) return;
    setSaving(mode);
    apiFetch(`${getBackendBaseURL()}/api/v1/auth/preferences`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "X-Expected-User-Id": userId,
      },
      body: JSON.stringify({ experience_mode: mode }),
    })
      .catch(() => undefined)
      .finally(() => {
        setSettings("context", { experience_mode: mode });
        setSaving(null);
        setOpen(false);
      });
  };

  const cards: {
    mode: ExperienceMode;
    label: string;
    tagline: string;
  }[] = [
    {
      mode: "easy",
      label: t.settings.experience.easyLabel,
      tagline: t.settings.experience.easyTagline,
    },
    {
      mode: "medium",
      label: t.settings.experience.mediumLabel,
      tagline: t.settings.experience.mediumTagline,
    },
    {
      mode: "hard",
      label: t.settings.experience.hardLabel,
      tagline: t.settings.experience.hardTagline,
    },
  ];

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => (next ? setOpen(true) : choose("medium"))}
    >
      <DialogContent
        data-treatment="paper"
        className="sm:max-w-lg"
        aria-describedby={undefined}
      >
        <DialogHeader className="items-center gap-3 text-center">
          <img
            src="/momentum/momos/lead.svg"
            alt=""
            aria-hidden="true"
            width={48}
            height={48}
            className="size-12"
          />
          <DialogTitle className="font-[family-name:var(--m-font-serif)] text-2xl font-normal">
            {t.settings.experience.chooserTitle}
          </DialogTitle>
          <p className="text-muted-foreground text-sm">
            {t.settings.experience.chooserSubtitle}
          </p>
        </DialogHeader>
        <div className="grid gap-3 sm:grid-cols-3">
          {cards.map((card) => (
            <button
              key={card.mode}
              type="button"
              disabled={saving !== null}
              onClick={() => choose(card.mode)}
              className={cn(
                "paper-card flex flex-col items-center gap-1 rounded-lg border p-4 text-center transition-colors",
                "hover:bg-muted/50 disabled:opacity-60",
              )}
            >
              <span className="font-semibold">{card.label}</span>
              <span className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
                {card.tagline}
              </span>
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => choose("medium")}
          disabled={saving !== null}
          className="text-muted-foreground hover:text-foreground mx-auto text-sm underline-offset-4 hover:underline"
        >
          {t.settings.experience.chooserSkip}
        </button>
      </DialogContent>
    </Dialog>
  );
}
