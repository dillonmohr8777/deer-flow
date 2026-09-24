"use client";

import { MessageSquarePlus } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import { BrandSignature } from "@/components/workspace/command-center/brand-signature";
import { BrandMotionToggle } from "@/components/workspace/command-center/workspace-appearance";
import { useI18n } from "@/core/i18n/hooks";
import { env } from "@/env";
import { cn } from "@/lib/utils";

export function WorkspaceHeader({ className }: { className?: string }) {
  const { t } = useI18n();
  const { state } = useSidebar();
  const pathname = usePathname();
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
        {state === "collapsed" ? (
          <div className="group-has-data-[collapsible=icon]/sidebar-wrapper:-translate-y flex w-full cursor-pointer items-center justify-center">
            <div className="text-primary block pt-1 font-serif group-hover/workspace-header:hidden">
              M
            </div>
            <SidebarTrigger className="hidden pl-2 group-hover/workspace-header:block" />
          </div>
        ) : (
          <div className="flex items-center justify-between gap-2">
            {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ? (
              <Link href="/" className="text-primary ml-2 font-serif">
                MomoBot
              </Link>
            ) : (
              <Link
                href="/workspace/command-center"
                className="ml-2 flex min-w-0 flex-1 flex-col gap-0.5"
                aria-label="MomoBot Command Center"
              >
                <span className="text-primary font-serif text-sm leading-none font-semibold">
                  MomoBot
                </span>
                <BrandSignature />
              </Link>
            )}
            {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" && (
              <BrandMotionToggle compact />
            )}
            <SidebarTrigger />
          </div>
        )}
      </div>
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname === "/workspace/chats/new"}
            asChild
          >
            <Link className="text-muted-foreground" href="/workspace/chats/new">
              <MessageSquarePlus size={16} />
              <span>{t.sidebar.newChat}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </>
  );
}
