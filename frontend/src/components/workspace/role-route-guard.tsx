"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/workspace/page-body";
import { useAgents } from "@/core/agents/hooks";
import { useIsClient, useIsRoleUnresolved } from "@/core/auth/AuthProvider";
import {
  CLIENT_NEW_CHAT_PATH,
  clientNewChatPath,
  isClientPath,
} from "@/core/auth/roles";
import { useI18n } from "@/core/i18n/hooks";

/**
 * Direct navigation by a client to an internal page shows a polite "not
 * available" page instead of the page. Convenience only: the Gateway answers
 * 403 to every internal route for a client, so nothing here protects data.
 */
export function RoleRouteGuard({ children }: { children: ReactNode }) {
  const isClient = useIsClient();
  const unresolved = useIsRoleUnresolved();
  const pathname = usePathname();
  const router = useRouter();
  const { t } = useI18n();
  // A new default chat would run without MomoBot Max's page around it: send
  // the client to their own agent (or MomoBot Max) once the agents list is in.
  const startsDefaultChat = isClient && pathname === CLIENT_NEW_CHAT_PATH;
  const { agents, isLoading: agentsLoading } = useAgents();

  useEffect(() => {
    if (startsDefaultChat && !agentsLoading) {
      router.replace(clientNewChatPath(agents));
    }
  }, [agents, agentsLoading, router, startsDefaultChat]);

  // Waiting for the agents list to pick where the new chat starts.
  if (unresolved || startsDefaultChat) return null;
  if (!isClient || isClientPath(pathname)) return <>{children}</>;
  return (
    <div className="flex size-full items-center justify-center p-6">
      <EmptyState
        momo="builder"
        title={t.common.pageNotAvailableTitle}
        action={
          <Button asChild variant="outline" size="sm">
            <Link href={clientNewChatPath(agents)}>{t.common.backToChat}</Link>
          </Button>
        }
      >
        {t.common.pageNotAvailableDescription}
      </EmptyState>
    </div>
  );
}
