"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/workspace/page-body";
import { useIsClient, useIsRoleUnresolved } from "@/core/auth/AuthProvider";
import { CLIENT_NEW_CHAT_PATH, isClientPath } from "@/core/auth/roles";
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
  // A new default chat would run without MomoBot Max's page around it.
  const startsDefaultChat = isClient && pathname === "/workspace/chats/new";

  useEffect(() => {
    if (startsDefaultChat) router.replace(CLIENT_NEW_CHAT_PATH);
  }, [router, startsDefaultChat]);

  if (unresolved) return null;
  if (!isClient || isClientPath(pathname)) return <>{children}</>;
  if (startsDefaultChat) return null;
  return (
    <div className="flex size-full items-center justify-center p-6">
      <EmptyState
        momo="builder"
        title={t.common.pageNotAvailableTitle}
        action={
          <Button asChild variant="outline" size="sm">
            <Link href={CLIENT_NEW_CHAT_PATH}>{t.common.backToChat}</Link>
          </Button>
        }
      >
        {t.common.pageNotAvailableDescription}
      </EmptyState>
    </div>
  );
}
