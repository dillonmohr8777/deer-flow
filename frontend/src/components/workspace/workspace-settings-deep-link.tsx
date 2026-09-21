"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";

import {
  openSettingsDialog,
  type SettingsSection,
  useSettingsDialog,
} from "./settings";

const SETTINGS_SECTIONS = new Set<SettingsSection>([
  "models",
  "account",
  "appearance",
  "channels",
  "memory",
  "subagents",
  "notification",
  "about",
]);

function asSettingsSection(value: string | null): SettingsSection | null {
  if (!value) return null;
  return SETTINGS_SECTIONS.has(value as SettingsSection)
    ? (value as SettingsSection)
    : null;
}

/**
 * Bridges the `?settings=<section>` query param to the shared settings dialog
 * store. It does not mount its own dialog — a single {@link SettingsDialogHost}
 * renders the one dialog — so a deep link can never race a second dialog opened
 * from the nav menu or command palette.
 */
export function WorkspaceSettingsDeepLink() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { open } = useSettingsDialog();
  const query = searchParams.toString();
  const activeLink = useRef<{ key: string; observedOpen: boolean } | null>(
    null,
  );

  useEffect(() => {
    const next = new URLSearchParams(query);
    const nextSection = asSettingsSection(next.get("settings"));
    if (!nextSection) {
      activeLink.current = null;
      return;
    }

    const key = JSON.stringify([pathname, nextSection, next.get("specialist")]);
    if (activeLink.current?.key !== key) {
      activeLink.current = { key, observedOpen: open };
      openSettingsDialog(nextSection);
      return;
    }

    if (open) {
      activeLink.current.observedOpen = true;
      return;
    }

    // The store opens after the initial closed render. Keep the query available
    // to lazy settings pages until we have actually observed open -> closed.
    if (!activeLink.current.observedOpen) return;
    activeLink.current.observedOpen = false;
    next.delete("settings");
    next.delete("specialist");
    const suffix = next.toString();
    router.replace(suffix ? `${pathname}?${suffix}` : pathname, {
      scroll: false,
    });
  }, [open, pathname, query, router]);

  return null;
}
