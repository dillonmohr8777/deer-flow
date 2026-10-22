"use client";

import { MessageSquarePlus } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { BrandMotionToggle } from "@/components/workspace/command-center/workspace-appearance";
import { useIsClient } from "@/core/auth/AuthProvider";
import { CLIENT_NEW_CHAT_PATH } from "@/core/auth/roles";
import { useI18n } from "@/core/i18n/hooks";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import { useSidebarExpanded } from "./use-sidebar-expanded";
import { WorkspaceSidebarTrigger } from "./workspace-sidebar-trigger";

export function WorkspaceHeader({ className }: { className?: string }) {
  const { t } = useI18n();
  const isSidebarExpanded = useSidebarExpanded();
  const pathname = usePathname();
  // A client has no Command Center, and every new chat is with MomoBot Max.
  const isClient = useIsClient();
  const homePath = isClient
    ? CLIENT_NEW_CHAT_PATH
    : "/workspace/command-center";
  const newChatPath = isClient ? CLIENT_NEW_CHAT_PATH : "/workspace/chats/new";
  const sidebarIsCollapsed = !isSidebarExpanded;
  return (
    <>
      <div
        className={cn(
          // min-h, not h: the expanded header stacks the MomoBot label over
          // the brand signature, which is taller than 48px and was clipped.
          "group/workspace-header flex min-h-12 flex-col justify-center py-1.5",
          className,
        )}
      >
        {sidebarIsCollapsed ? (
          <div className="group-has-data-[collapsible=icon]/sidebar-wrapper:-translate-y flex w-full cursor-pointer items-center justify-center">
            <div className="text-primary block pt-1 font-serif group-hover/workspace-header:hidden">
              M
            </div>
            <WorkspaceSidebarTrigger className="hidden pl-2 group-hover/workspace-header:block" />
          </div>
        ) : (
          <div className="flex items-center justify-between gap-2">
            {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ? (
              <Link href="/" className="text-primary ml-2 font-serif">
                MomoBot
              </Link>
            ) : (
              // The product name leads the sidebar on its own; the Momentum
              // signature sits at the far end of the sidebar footer
              // (workspace-sidebar.tsx) instead of stacked under it.
              <Link
                href={homePath}
                className="ml-2 min-w-0 flex-1"
                aria-label={isClient ? "MomoBot" : "MomoBot Command Center"}
              >
                <span className="text-primary block font-serif text-2xl leading-none font-bold tracking-tight">
                  MomoBot
                </span>
              </Link>
            )}
            {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" && (
              <BrandMotionToggle compact />
            )}
            <WorkspaceSidebarTrigger />
          </div>
        )}
      </div>
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton isActive={pathname === newChatPath} asChild>
            <Link className="text-muted-foreground" href={newChatPath}>
              <MessageSquarePlus size={16} />
              <span>{t.sidebar.newChat}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </>
  );
}
