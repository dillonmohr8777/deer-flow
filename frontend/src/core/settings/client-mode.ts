import { useCallback } from "react";

import { useAuth } from "@/core/auth/AuthProvider";
import { isClientUser } from "@/core/auth/roles";

import { useLocalSettings } from "./hooks";
import type { LocalSettings } from "./local";

export type DeveloperDetailsMode = LocalSettings["developerDetails"]["mode"];

export function isStaffRole(
  user: { system_role?: string } | null | undefined,
): boolean {
  return user?.system_role === "admin" || user?.system_role === "exec";
}

/**
 * Clean Client Mode hides raw developer telemetry (token counters, context
 * window percentages, and file-diff chrome) so business owners see plain-English
 * deliverable status instead of code-editor jargon.
 *
 * - `client` users are always in Clean Client Mode.
 * - Non-staff signed-in users (`user` role, e.g. client/sandbox workspaces) and
 *   Easy mode default to Clean Client Mode unless explicitly toggled off.
 * - Staff (`admin` / `exec`) in medium/hard mode keep developer details visible
 *   by default, and can toggle Clean Client Mode on/off at any time.
 */
export function resolveCleanClientMode({
  user,
  experienceMode,
  developerDetailsMode = "auto",
}: {
  user: { system_role?: string } | null | undefined;
  experienceMode?: LocalSettings["context"]["experience_mode"];
  developerDetailsMode?: DeveloperDetailsMode;
}): boolean {
  if (isClientUser(user)) {
    return true;
  }
  if (developerDetailsMode === "show") {
    return false;
  }
  if (developerDetailsMode === "hide") {
    return true;
  }
  if (experienceMode === "easy") {
    return true;
  }
  if (user && !isStaffRole(user)) {
    return true;
  }
  return false;
}

export function useCleanClientMode() {
  const { user } = useAuth();
  const [localSettings, setLocalSettings] = useLocalSettings();
  const isClient = isClientUser(user);
  const cleanClientMode = resolveCleanClientMode({
    user,
    experienceMode: localSettings.context.experience_mode,
    developerDetailsMode: localSettings.developerDetails?.mode ?? "auto",
  });

  const setShowDeveloperDetails = useCallback(
    (show: boolean) => {
      if (isClient) {
        return;
      }
      setLocalSettings("developerDetails", {
        mode: show ? "show" : "hide",
      });
    },
    [isClient, setLocalSettings],
  );

  return {
    cleanClientMode,
    canToggleDeveloperDetails: !isClient && Boolean(user),
    showDeveloperDetails: !cleanClientMode,
    setShowDeveloperDetails,
  };
}
