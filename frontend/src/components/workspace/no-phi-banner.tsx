"use client";

import { ShieldAlertIcon } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { useI18n } from "@/core/i18n/hooks";
import { useNoPhiWorkspace } from "@/core/workspaces/hooks";

/**
 * Persistent notice for health-sector workspaces. The server decides the flag
 * (admin-owned, returned by `GET /api/workspaces`); there is no dismiss button
 * on purpose, so the reminder stays on every page of the workspace.
 */
export function NoPhiBanner() {
  const { t } = useI18n();
  const noPhi = useNoPhiWorkspace();
  if (!noPhi) return null;
  return (
    <Alert
      role="note"
      data-testid="no-phi-banner"
      className="rounded-none border-x-0 border-t-0"
    >
      <ShieldAlertIcon className="size-4" aria-hidden />
      <AlertTitle>{t.workspace.noPhiBanner}</AlertTitle>
      <AlertDescription>{t.workspace.noPhiBannerDetail}</AlertDescription>
    </Alert>
  );
}
