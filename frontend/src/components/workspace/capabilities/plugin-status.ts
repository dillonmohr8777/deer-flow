import type { capabilityCopy } from "@/core/capabilities/copy";
import type { CapabilityInstallation } from "@/core/capabilities/types";
import type { Translations } from "@/core/i18n/locales/types";

export type PluginStatusTone = "ok" | "attention" | "idle" | "unknown";

/**
 * A catalog row's state, said honestly: a status read that failed is
 * "unavailable", never "not configured", and only a configured or connected
 * installation reads as ok.
 */
export function getPluginStatus(
  adapter: string,
  status: CapabilityInstallation | undefined,
  unavailable: boolean | undefined,
  t: Translations,
  labels: ReturnType<typeof capabilityCopy>,
): { label: string; tone: PluginStatusTone } {
  if (unavailable) return { label: labels.adapterError, tone: "unknown" };
  if (status) {
    if (status.auth_status === "connected")
      return { label: labels.connected, tone: "ok" };
    if (status.auth_status === "required")
      return { label: labels.required, tone: "attention" };
    if (status.auth_status === "configured")
      return { label: labels.configured, tone: "ok" };
    return { label: labels.installed, tone: "ok" };
  }
  if (adapter === "guide")
    return { label: t.capabilities.directory.candidate, tone: "idle" };
  if (adapter === "lark")
    return { label: t.capabilities.notInstalled, tone: "idle" };
  return { label: labels.notConfigured, tone: "idle" };
}

/**
 * Whether a row belongs under Connected: installed, readable, not waiting on
 * an account, and switched on and selectable. Anything short of that still
 * needs someone, so it stays with what is available to connect.
 */
export function isPluginConnected(
  status:
    | Pick<CapabilityInstallation, "auth_status" | "enabled" | "selectable">
    | undefined,
  unavailable?: boolean,
): boolean {
  return (
    !!status &&
    !unavailable &&
    status.auth_status !== "required" &&
    status.enabled !== false &&
    status.selectable !== false
  );
}
