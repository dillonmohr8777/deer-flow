"use client";

import {
  Inbox,
  LampDesk,
  Menu,
  MessagesSquare,
  Network,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useSidebar } from "@/components/ui/sidebar";
import { useDeskEnabled } from "@/core/features";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

type Tab = {
  href: string;
  label: string;
  icon: LucideIcon;
  active: (pathname: string) => boolean;
};

/** Inside a conversation the composer owns the bottom edge, so the bar steps aside. */
export function isConversationPath(pathname: string) {
  return /\/chats\/(?!new$)[^/]+/.test(pathname);
}

const TAB =
  "relative flex min-h-14 min-w-0 flex-1 flex-col items-center justify-center gap-0.5 px-1 pt-1.5 pb-1 text-xs font-bold outline-offset-[-3px]";

/**
 * Phone-only primary navigation. On desktop the sidebar is the nav; below
 * 768px the sidebar is a sheet, so the destinations you use every day sit
 * at thumb reach here and "More" opens that sheet for the rest.
 */
export function WorkspaceTabBar() {
  const { t } = useI18n();
  const pathname = usePathname();
  const { isMobile, openMobile, setOpenMobile } = useSidebar();
  const { enabled: deskEnabled } = useDeskEnabled();

  if (!isMobile || isConversationPath(pathname)) return null;

  const tabs: Tab[] = [
    {
      href: "/workspace/chats/new",
      label: "Chat",
      icon: MessagesSquare,
      active: (p) => p.startsWith("/workspace/chats"),
    },
    ...(deskEnabled
      ? [
          {
            href: "/workspace/desk",
            label: "Desk",
            icon: LampDesk,
            active: (p: string) => p === "/workspace/desk",
          },
          {
            href: "/workspace/board",
            label: "Board",
            icon: Inbox,
            active: (p: string) => p === "/workspace/board",
          },
        ]
      : []),
    {
      href: "/workspace/command-center",
      label: "Command",
      icon: Network,
      active: (p) => p === "/workspace/command-center",
    },
  ];

  return (
    <nav
      aria-label="Workspace"
      data-slot="workspace-tab-bar"
      data-testid="workspace-tab-bar"
      className="bg-card border-border flex shrink-0 border-t pb-[env(safe-area-inset-bottom)] shadow-[0_-1px_0_color-mix(in_srgb,var(--foreground)_10%,transparent)] md:hidden"
    >
      {tabs.map(({ href, label, icon: Icon, active }) => {
        const current = active(pathname);
        return (
          <Link
            key={href}
            href={href}
            aria-current={current ? "page" : undefined}
            className={cn(
              TAB,
              current ? "text-primary" : "text-muted-foreground",
            )}
          >
            {/* The selected tab carries a royal mark on its top edge, like a
                folder tab pulled up out of the drawer. */}
            {current && (
              <span
                aria-hidden
                className="bg-primary absolute inset-x-3 top-0 h-[3px] rounded-b-[1px]"
              />
            )}
            <Icon className="size-[22px]" aria-hidden />
            <span className="truncate">{label}</span>
          </Link>
        );
      })}
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={openMobile}
        onClick={() => setOpenMobile(true)}
        className={cn(TAB, "text-muted-foreground")}
      >
        <Menu className="size-[22px]" aria-hidden />
        <span className="truncate">{t.common.more}</span>
      </button>
    </nav>
  );
}
