"use client";

import {
  BotIcon,
  BellIcon,
  CableIcon,
  InfoIcon,
  BrainIcon,
  GraduationCapIcon,
  KeyRoundIcon,
  PaletteIcon,
  ShieldCheckIcon,
  UsersRoundIcon,
  UserIcon,
} from "lucide-react";
import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import styles from "./settings-dialog.module.css";

function SettingsPageLoading() {
  return (
    <p role="status" className="text-muted-foreground py-8 text-center text-sm">
      Loading…
    </p>
  );
}

const AccountSettingsPage = dynamic(
  () =>
    import("./account-settings-page").then(
      (module) => module.AccountSettingsPage,
    ),
  { loading: SettingsPageLoading },
);
const SecuritySettingsPage = dynamic(
  () =>
    import("./security-settings-page").then(
      (module) => module.SecuritySettingsPage,
    ),
  { loading: SettingsPageLoading },
);
const AppearanceSettingsPage = dynamic(
  () =>
    import("./appearance-settings-page").then(
      (module) => module.AppearanceSettingsPage,
    ),
  { loading: SettingsPageLoading },
);
const ChannelsSettingsPage = dynamic(
  () =>
    import("./channels-settings-page").then(
      (module) => module.ChannelsSettingsPage,
    ),
  { loading: SettingsPageLoading },
);
const MemorySettingsPage = dynamic(
  () =>
    import("./memory-settings-page").then(
      (module) => module.MemorySettingsPage,
    ),
  { loading: SettingsPageLoading },
);
const NotificationSettingsPage = dynamic(
  () =>
    import("./notification-settings-page").then(
      (module) => module.NotificationSettingsPage,
    ),
  { loading: SettingsPageLoading },
);
const ExperienceSettingsPage = dynamic(
  () =>
    import("./experience-settings-page").then(
      (module) => module.ExperienceSettingsPage,
    ),
  { loading: SettingsPageLoading },
);
const SubagentSettingsPage = dynamic(
  () =>
    import("./subagent-settings-page").then(
      (module) => module.SubagentSettingsPage,
    ),
  { loading: SettingsPageLoading },
);
const ModelSettingsPage = dynamic(
  () =>
    import("./model-settings-page").then((module) => module.ModelSettingsPage),
  { loading: SettingsPageLoading },
);
const AboutSettingsPage = dynamic(
  () =>
    import("./about-settings-page").then((module) => module.AboutSettingsPage),
  { loading: SettingsPageLoading },
);
const AuditSettingsPage = dynamic(
  () =>
    import("./audit-settings-page").then((module) => module.AuditSettingsPage),
  { loading: SettingsPageLoading },
);

export type SettingsSection =
  | "models"
  | "account"
  | "security"
  | "appearance"
  | "channels"
  | "memory"
  | "subagents"
  | "notification"
  | "experience"
  | "audit"
  | "about";

type SettingsDialogProps = React.ComponentProps<typeof Dialog> & {
  defaultSection?: SettingsSection;
};

export function SettingsDialog(props: SettingsDialogProps) {
  const { defaultSection = "appearance", ...dialogProps } = props;
  const { t } = useI18n();
  const [activeSection, setActiveSection] =
    useState<SettingsSection>(defaultSection);
  const navRef = useRef<HTMLElement>(null);

  useEffect(() => {
    // On phones the sections are a sideways rail: keep the selected one in
    // view, or a deep link can land on a tab scrolled off the right edge.
    navRef.current
      ?.querySelector<HTMLElement>(`[data-section="${activeSection}"]`)
      ?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [activeSection]);

  useEffect(() => {
    // When opening the dialog, ensure the active section follows the caller's intent.
    // This allows triggers like "About" to open the dialog directly on that page.
    if (dialogProps.open) {
      setActiveSection(defaultSection);
    }
  }, [defaultSection, dialogProps.open]);

  const sections = useMemo(
    () => [
      { id: "models", label: t.settings.sections.models, icon: BotIcon },
      {
        id: "account",
        label: t.settings.sections.account,
        icon: UserIcon,
      },
      {
        id: "security",
        label: t.settings.sections.security,
        icon: KeyRoundIcon,
      },
      {
        id: "appearance",
        label: t.settings.sections.appearance,
        icon: PaletteIcon,
      },
      {
        id: "notification",
        label: t.settings.sections.notification,
        icon: BellIcon,
      },
      {
        id: "experience",
        label: t.settings.sections.experience,
        icon: GraduationCapIcon,
      },
      {
        id: "channels",
        label: t.settings.sections.channels,
        icon: CableIcon,
      },
      {
        id: "memory",
        label: t.settings.sections.memory,
        icon: BrainIcon,
      },
      {
        id: "subagents",
        label: t.settings.sections.subagents,
        icon: UsersRoundIcon,
      },
      {
        id: "audit",
        label: t.settings.sections.audit,
        icon: ShieldCheckIcon,
      },
      { id: "about", label: t.settings.sections.about, icon: InfoIcon },
    ],
    [
      t.settings.sections.models,
      t.settings.sections.account,
      t.settings.sections.security,
      t.settings.sections.appearance,
      t.settings.sections.channels,
      t.settings.sections.memory,
      t.settings.sections.subagents,
      t.settings.sections.notification,
      t.settings.sections.experience,
      t.settings.sections.audit,
      t.settings.sections.about,
    ],
  );
  return (
    <Dialog
      {...dialogProps}
      onOpenChange={(open) => props.onOpenChange?.(open)}
    >
      <DialogContent
        className="flex h-[calc(100dvh-2rem)] max-h-[calc(100dvh-2rem)] flex-col gap-3 p-4 sm:h-[75vh] sm:max-w-5xl sm:gap-4 sm:p-6 md:max-w-6xl"
        aria-describedby={undefined}
        onOpenAutoFocus={(event) => {
          // Radix focuses the first nav item (Models) while another section
          // is selected: two highlights at once. Focus the selected one.
          event.preventDefault();
          navRef.current
            ?.querySelector<HTMLElement>(`[data-section="${defaultSection}"]`)
            ?.focus();
        }}
      >
        <DialogHeader className="gap-1">
          <DialogTitle>{t.settings.title}</DialogTitle>
          <p className="text-muted-foreground text-sm">
            {t.settings.description}
          </p>
        </DialogHeader>
        {/* minmax(0,1fr), not the implicit auto column: on phones the panel
            otherwise grows to its widest child and runs past the dialog. */}
        <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)] gap-3 md:grid-cols-[220px_minmax(0,1fr)] md:grid-rows-1 md:gap-4">
          <nav
            ref={navRef}
            aria-label={t.settings.title}
            className={cn(
              "bg-sidebar min-h-0 overflow-x-auto rounded-lg border p-1.5 md:overflow-y-auto md:p-2",
              styles.tabFade,
            )}
          >
            <ul className="flex gap-1 md:block md:space-y-1 md:pr-1">
              {sections.map(({ id, label, icon: Icon }) => {
                const active = activeSection === id;
                return (
                  <li key={id} className="shrink-0">
                    <button
                      type="button"
                      data-section={id}
                      aria-current={active ? "page" : undefined}
                      onClick={() => setActiveSection(id as SettingsSection)}
                      className={cn(
                        "flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors md:gap-3",
                        active
                          ? "bg-primary text-primary-foreground shadow-sm"
                          : "text-muted-foreground hover:bg-muted hover:text-foreground",
                      )}
                    >
                      <Icon className="size-4" />
                      <span>{label}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </nav>
          <ScrollArea className="h-full min-h-0 rounded-lg border">
            <div className="space-y-8 p-4 sm:p-6">
              {activeSection === "models" && <ModelSettingsPage />}
              {activeSection === "account" && <AccountSettingsPage />}
              {activeSection === "security" && <SecuritySettingsPage />}
              {activeSection === "appearance" && <AppearanceSettingsPage />}
              {activeSection === "memory" && <MemorySettingsPage />}
              {activeSection === "subagents" && <SubagentSettingsPage />}
              {activeSection === "notification" && <NotificationSettingsPage />}
              {activeSection === "experience" && <ExperienceSettingsPage />}
              {activeSection === "channels" && <ChannelsSettingsPage />}
              {activeSection === "audit" && <AuditSettingsPage />}
              {activeSection === "about" && <AboutSettingsPage />}
            </div>
          </ScrollArea>
        </div>
      </DialogContent>
    </Dialog>
  );
}
