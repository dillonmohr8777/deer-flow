import type { CapabilityInstallation } from "@/core/capabilities/types";

/**
 * What a catalog row's one button actually does, so the label can say it.
 * Connect starts an account flow, Configure opens settings the viewer may
 * change, Details only reads, and a setup guide is reference material.
 */
export type PluginAction = "connect" | "configure" | "details" | "guide";

export function getPluginAction(
  adapter: string,
  status: CapabilityInstallation | undefined,
  canManage: boolean,
): PluginAction {
  if (status) {
    if (status.auth_status === "required") return "connect";
    return canManage ? "configure" : "details";
  }
  if (adapter === "guide") return "guide";
  if (!canManage) return "details";
  // Lark installs the managed integration and then connects an account.
  if (adapter === "lark") return "connect";
  return "configure";
}
