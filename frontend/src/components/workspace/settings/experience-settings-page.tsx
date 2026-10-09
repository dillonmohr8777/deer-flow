"use client";

import { CheckIcon } from "lucide-react";

import { useI18n } from "@/core/i18n/hooks";
import { useLocalSettings } from "@/core/settings";
import { cn } from "@/lib/utils";

import { SettingsSection } from "./settings-section";

type ExperienceMode = "easy" | "medium" | "hard";

export function ExperienceSettingsPage() {
  const { t } = useI18n();
  const [settings, setSettings] = useLocalSettings();
  const current: ExperienceMode = settings.context.experience_mode ?? "medium";

  const cards: {
    mode: ExperienceMode;
    label: string;
    tagline: string;
    description: string;
  }[] = [
    {
      mode: "easy",
      label: t.settings.experience.easyLabel,
      tagline: t.settings.experience.easyTagline,
      description: t.settings.experience.easyDescription,
    },
    {
      mode: "medium",
      label: t.settings.experience.mediumLabel,
      tagline: t.settings.experience.mediumTagline,
      description: t.settings.experience.mediumDescription,
    },
    {
      mode: "hard",
      label: t.settings.experience.hardLabel,
      tagline: t.settings.experience.hardTagline,
      description: t.settings.experience.hardDescription,
    },
  ];

  return (
    <SettingsSection
      title={t.settings.experience.title}
      description={t.settings.experience.description}
    >
      <div className="grid gap-3 sm:grid-cols-3">
        {cards.map((card) => {
          const selected = current === card.mode;
          return (
            <button
              key={card.mode}
              type="button"
              aria-pressed={selected}
              onClick={() =>
                setSettings("context", { experience_mode: card.mode })
              }
              className={cn(
                "flex flex-col gap-2 rounded-lg border p-4 text-left transition-colors",
                selected ? "border-primary bg-primary/5" : "hover:bg-muted/50",
              )}
            >
              <div className="flex items-center justify-between">
                <span className="font-semibold">{card.label}</span>
                {selected && (
                  <CheckIcon className="text-primary size-4 shrink-0" />
                )}
              </div>
              <span className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
                {card.tagline}
              </span>
              <p className="text-muted-foreground text-sm">
                {card.description}
              </p>
            </button>
          );
        })}
      </div>
    </SettingsSection>
  );
}
