"use client";

import { useEffect, useState } from "react";

import { fetch as apiFetch } from "@/core/api/fetcher";
import { useAuth } from "@/core/auth/AuthProvider";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { useLocalSettings } from "@/core/settings";
import { MODE_FOR_EXPERIENCE } from "@/core/settings/local";
import { isStaticWebsiteOnly } from "@/core/static-mode";
import { cn } from "@/lib/utils";

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../ui/dialog";

type ExperienceMode = "easy" | "medium" | "hard";

const MODES: ExperienceMode[] = ["easy", "medium", "hard"];

function saveExperienceMode(userId: string, mode: ExperienceMode) {
  return apiFetch(`${getBackendBaseURL()}/api/v1/auth/preferences`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      "X-Expected-User-Id": userId,
    },
    body: JSON.stringify({
      experience_mode: mode,
      mode: MODE_FOR_EXPERIENCE[mode],
    }),
  }).catch(() => undefined);
}

/*
 * Always-visible Easy / Medium / Hard switch for the sidebar (Dillon, Oct 22:
 * "where's the easy mode, the hard mode, the medium?"). Same preference as the
 * first-sign-in chooser below.
 */
export function ExperienceModeSwitch() {
  const { t } = useI18n();
  const { user } = useAuth();
  const [settings, setSettings] = useLocalSettings();
  const userId =
    !isStaticWebsiteOnly() && user?.id !== "default" ? user?.id : undefined;
  const current = settings.context.experience_mode ?? "medium";
  const labels: Record<ExperienceMode, string> = {
    easy: t.settings.experience.easyLabel,
    medium: t.settings.experience.mediumLabel,
    hard: t.settings.experience.hardLabel,
  };
  return (
    <div
      role="radiogroup"
      aria-label={t.settings.experience.chooserTitle}
      className="bg-muted/60 mx-2 mt-2 grid grid-cols-3 gap-1 rounded-lg p-1"
    >
      {MODES.map((mode) => (
        <button
          key={mode}
          type="button"
          role="radio"
          aria-checked={current === mode}
          onClick={() => {
            setSettings("context", {
        experience_mode: mode,
        mode: MODE_FOR_EXPERIENCE[mode],
      });
            if (userId) void saveExperienceMode(userId, mode);
          }}
          className={cn(
            "min-h-9 rounded-md text-xs font-semibold transition-colors",
            current === mode
              ? "bg-background text-foreground shadow-xs"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {labels[mode]}
        </button>
      ))}
    </div>
  );
}

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
    void saveExperienceMode(userId, mode).finally(() => {
      setSettings("context", {
        experience_mode: mode,
        mode: MODE_FOR_EXPERIENCE[mode],
      });
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
