"use client";

import {
  BotIcon,
  GraduationCap,
  Info,
  UsersRound,
  Hash,
  CalendarClock,
  Inbox,
  MessagesSquare,
  LampDesk,
  Network,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  SidebarGroup,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useAgentsApiEnabled } from "@/core/agents";
import { useAuth } from "@/core/auth/AuthProvider";
import { useBoardThreads } from "@/core/board";
import { useDeskEnabled, useMomentumInternalEnabled } from "@/core/features";
import { useI18n } from "@/core/i18n/hooks";
import { useBrandKit } from "@/core/momobot-brand";

export function WorkspaceNavChatList() {
  const { t } = useI18n();
  const pathname = usePathname();
  const { enabled: agentsEnabled } = useAgentsApiEnabled();
  const { enabled: deskEnabled } = useDeskEnabled();
  const { enabled: internalEnabled } = useMomentumInternalEnabled();
  const { data: brandKit } = useBrandKit();
  const { user } = useAuth();
  const isAdmin = user?.system_role === "admin";
  // Threads with a Momo draft waiting on the owner; same query Desk's
  // Approvals panel runs, so React Query shares one cache entry.
  const waitingApproval = useBoardThreads({
    status: "drafted",
    enabled: deskEnabled,
  });
  const waitingCount = deskEnabled ? (waitingApproval.data?.length ?? 0) : 0;
  return (
    <SidebarGroup className="pt-1">
      <SidebarMenu>
        {/* Owner-only: exists solely on the private instance. */}
        {deskEnabled && (
          <SidebarMenuItem>
            <SidebarMenuButton
              isActive={pathname === "/workspace/desk"}
              asChild
            >
              <Link className="text-muted-foreground" href="/workspace/desk">
                <LampDesk />
                <span>Desk</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}
        {/* Owner-only: same private-instance boundary as Desk. */}
        {deskEnabled && (
          <SidebarMenuItem>
            <SidebarMenuButton
              isActive={pathname === "/workspace/board"}
              asChild
            >
              <Link
                className="text-muted-foreground"
                href="/workspace/board"
                aria-label={
                  waitingCount > 0
                    ? `Board, ${waitingCount} waiting on you`
                    : undefined
                }
              >
                <Inbox />
                <span>Board</span>
              </Link>
            </SidebarMenuButton>
            {waitingCount > 0 && (
              // The link's own aria-label already carries the count; hide
              // this visual badge from assistive tech so it isn't announced
              // a second time as an unlabeled number.
              <SidebarMenuBadge aria-hidden="true">
                {waitingCount}
              </SidebarMenuBadge>
            )}
          </SidebarMenuItem>
        )}
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname === "/workspace/approvals"}
            asChild
          >
            <Link className="text-muted-foreground" href="/workspace/approvals">
              <ShieldCheck />
              <span>Approvals</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        {/* Momentum staff only: the agency's own workspace plus a staff role. */}
        {internalEnabled && (
          <SidebarMenuItem>
            <SidebarMenuButton
              isActive={pathname === "/workspace/team"}
              asChild
            >
              <Link className="text-muted-foreground" href="/workspace/team">
                <Hash />
                <span>Team</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}
        {/* Admins only, keeps the team sidebar short. */}
        {isAdmin && (
          <SidebarMenuItem>
            <SidebarMenuButton
              isActive={pathname === "/workspace/command-center"}
              asChild
            >
              <Link
                className="text-muted-foreground"
                href="/workspace/command-center"
              >
                <Network />
                <span>Command Center</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}
        <SidebarMenuItem>
          <SidebarMenuButton isActive={pathname === "/workspace/chats"} asChild>
            <Link className="text-muted-foreground" href="/workspace/chats">
              <MessagesSquare />
              <span>{t.sidebar.chats}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        {/* Admins only, keeps the team sidebar short. */}
        {isAdmin && (
          <SidebarMenuItem>
            {agentsEnabled ? (
              <SidebarMenuButton
                isActive={pathname.startsWith("/workspace/agents")}
                asChild
              >
                <Link
                  className="text-muted-foreground"
                  href="/workspace/agents"
                >
                  <BotIcon />
                  <span>{t.sidebar.agents}</span>
                </Link>
              </SidebarMenuButton>
            ) : (
              // Disabled: aria-disabled drives the sidebar CVA to suppress
              // pointer events on the button, so wrap it in a hoverable span
              // that still surfaces the "feature not enabled" tooltip for mouse
              // users. The button stays in the tab order (no tabIndex={-1}) and
              // is wired via aria-describedby to a visually-hidden reason, so
              // keyboard and screen-reader users also learn why it is disabled.
              <Tooltip>
                <TooltipTrigger asChild>
                  {/* cursor-not-allowed lives on the span (the element that
                    still receives pointer events), not the inert button. */}
                  <span className="block w-full cursor-not-allowed">
                    <SidebarMenuButton
                      className="text-muted-foreground/50"
                      aria-disabled
                      aria-describedby="agents-disabled-reason"
                    >
                      <BotIcon />
                      <span>{t.sidebar.agents}</span>
                    </SidebarMenuButton>
                    <span id="agents-disabled-reason" className="sr-only">
                      {t.sidebar.agentsDisabledTooltip}
                    </span>
                  </span>
                </TooltipTrigger>
                <TooltipContent side="right">
                  {t.sidebar.agentsDisabledTooltip}
                </TooltipContent>
              </Tooltip>
            )}
          </SidebarMenuItem>
        )}
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/scheduled-tasks")}
            asChild
          >
            <Link
              className="text-muted-foreground"
              href="/workspace/scheduled-tasks"
            >
              <CalendarClock />
              <span>{t.sidebar.scheduledTasks}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        {/* Only when the server has the private brand kit mounted. */}
        {brandKit && (
          <>
            <SidebarMenuItem>
              <SidebarMenuButton
                isActive={pathname === "/workspace/lineup"}
                asChild
              >
                <Link
                  className="text-muted-foreground"
                  href="/workspace/lineup"
                >
                  <UsersRound />
                  <span>MomoBot Agents</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
            <SidebarMenuItem>
              <SidebarMenuButton
                isActive={pathname === "/workspace/about"}
                asChild
              >
                <Link className="text-muted-foreground" href="/workspace/about">
                  <Info />
                  <span>About MomoBot</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </>
        )}
        {/* Momentum staff only, same gate as Team. */}
        {internalEnabled && (
          <SidebarMenuItem>
            <SidebarMenuButton
              isActive={pathname === "/workspace/academy"}
              asChild
            >
              <Link className="text-muted-foreground" href="/workspace/academy">
                <GraduationCap />
                <span>AI Academy</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}
      </SidebarMenu>
    </SidebarGroup>
  );
}
