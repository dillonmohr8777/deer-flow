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
  Newspaper,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { useAgents, useAgentsApiEnabled } from "@/core/agents";
import {
  useAuth,
  useIsClient,
  useIsRoleUnresolved,
} from "@/core/auth/AuthProvider";
import { useBoardThreads } from "@/core/board";
import { useDeskEnabled, useMomentumInternalEnabled } from "@/core/features";
import { useI18n } from "@/core/i18n/hooks";
import { MOMO_DAILY_NAME, MOMO_DAILY_PATH } from "@/core/momo-daily";
import { useBrandKit } from "@/core/momobot-brand";

import { ExperienceModeSwitch } from "./experience-mode-chooser";
import { WorkspaceSelector } from "./workspace-selector";

/**
 * The client version of MomoBot: chats, The Momo Daily (part of the base
 * subscription), the MomoBot lineup and About, nothing internal. (New chat
 * lives in the sidebar header.)
 */
function ClientNavList({ showBrandKit }: { showBrandKit: boolean }) {
  const { t } = useI18n();
  const pathname = usePathname();
  return (
    <SidebarGroup className="pt-1">
      <WorkspaceSelector />
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton isActive={pathname === "/workspace/inbox"} asChild>
            <Link className="text-muted-foreground" href="/workspace/inbox">
              <Inbox />
              <span>Client inbox</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>

        <SidebarMenuItem>
          <SidebarMenuButton isActive={pathname === "/workspace/chats"} asChild>
            <Link className="text-muted-foreground" href="/workspace/chats">
              <MessagesSquare />
              <span>{t.sidebar.chats}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith(MOMO_DAILY_PATH)}
            asChild
          >
            <Link className="text-muted-foreground" href={MOMO_DAILY_PATH}>
              <Newspaper />
              <span>{MOMO_DAILY_NAME}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        {showBrandKit && (
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
                  <span>{t.sidebar.momobotAgents}</span>
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
                  <span>{t.sidebar.aboutMomobot}</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </>
        )}
      </SidebarMenu>
    </SidebarGroup>
  );
}

export function WorkspaceNavChatList() {
  const { t } = useI18n();
  const pathname = usePathname();
  const isClient = useIsClient();
  const unresolved = useIsRoleUnresolved();
  const { enabled: agentsEnabled } = useAgentsApiEnabled();
  const { agents } = useAgents();
  // The backend lists momobot-max only when it is on and this role may run it.
  const maxAvailable =
    agentsEnabled && agents.some((agent) => agent.name === "momobot-max");
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
  if (unresolved) return null;
  if (isClient) return <ClientNavList showBrandKit={Boolean(brandKit)} />;
  // Oct 22 (Dillon: "too many things on the sidebar ... make it easier"): the
  // team sees MomoBot Max and the everyday pages; admin tools sit in one group.
  return (
    <>
      <SidebarGroup className="pt-1">
        <SidebarMenu>
          {maxAvailable && (
            <SidebarMenuItem>
              <SidebarMenuButton
                isActive={pathname.startsWith("/workspace/agents/momobot-max")}
                asChild
              >
                <Link
                  className="text-muted-foreground"
                  href="/workspace/agents/momobot-max/chats/new"
                >
                  <Sparkles />
                  <span>MomoBot Max</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          )}
          <SidebarMenuItem>
            <SidebarMenuButton
              isActive={pathname === "/workspace/chats"}
              asChild
            >
              <Link className="text-muted-foreground" href="/workspace/chats">
                <MessagesSquare />
                <span>{t.sidebar.chats}</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton
              isActive={pathname === "/workspace/inbox"}
              asChild
            >
              <Link className="text-muted-foreground" href="/workspace/inbox">
                <Inbox />
                <span>Client inbox</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
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
          {internalEnabled && (
            <SidebarMenuItem>
              <SidebarMenuButton
                isActive={pathname === "/workspace/academy"}
                asChild
              >
                <Link
                  className="text-muted-foreground"
                  href="/workspace/academy"
                >
                  <GraduationCap />
                  <span>AI Academy</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          )}
          {brandKit && (
            <SidebarMenuItem>
              <SidebarMenuButton
                isActive={pathname === "/workspace/about"}
                asChild
              >
                <Link className="text-muted-foreground" href="/workspace/about">
                  <Info />
                  <span>{t.sidebar.aboutMomobot}</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          )}
        </SidebarMenu>
        <ExperienceModeSwitch />
      </SidebarGroup>
      {isAdmin && (
        <SidebarGroup>
          <SidebarGroupLabel>Admin</SidebarGroupLabel>
          <SidebarMenu>
            {deskEnabled && (
              <SidebarMenuItem>
                <SidebarMenuButton
                  isActive={pathname === "/workspace/desk"}
                  asChild
                >
                  <Link
                    className="text-muted-foreground"
                    href="/workspace/desk"
                  >
                    <LampDesk />
                    <span>Desk</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            )}
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
                  // The link's aria-label carries the count; the badge is visual only.
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
                <Link
                  className="text-muted-foreground"
                  href="/workspace/approvals"
                >
                  <ShieldCheck />
                  <span>Approvals</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
            {internalEnabled && (
              <SidebarMenuItem>
                <SidebarMenuButton
                  isActive={pathname === "/workspace/team"}
                  asChild
                >
                  <Link
                    className="text-muted-foreground"
                    href="/workspace/team"
                  >
                    <Hash />
                    <span>Team</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            )}
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
            {agentsEnabled && (
              <SidebarMenuItem>
                <SidebarMenuButton
                  isActive={pathname === "/workspace/agents"}
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
              </SidebarMenuItem>
            )}
            {brandKit && (
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
                    <span>{t.sidebar.momobotAgents}</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            )}
          </SidebarMenu>
        </SidebarGroup>
      )}
    </>
  );
}
