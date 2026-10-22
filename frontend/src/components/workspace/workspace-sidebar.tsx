"use client";

import { Scraps } from "@/components/momentum/scraps";
import {
  Sidebar,
  SidebarHeader,
  SidebarContent,
  SidebarFooter,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";
import { useWorkspaceAppearance } from "@/components/workspace/command-center/appearance-provider";
import { useIsClient, useIsRoleUnresolved } from "@/core/auth/AuthProvider";
import { cn } from "@/lib/utils";

import { WorkspaceChannelsList } from "./channels/workspace-channels-list";
import { BackgroundJobs } from "./command-center/background-jobs";
import { BrandSignature } from "./command-center/brand-signature";
import { PluginNavigation } from "./plugin-navigation";
import { ProjectsSection } from "./projects-section";
import { RecentChatList } from "./recent-chat-list";
import { ThreadDeleteDialogProvider } from "./thread-delete-dialog";
import { useSidebarExpanded } from "./use-sidebar-expanded";
import { WorkspaceHeader } from "./workspace-header";
import { WorkspaceNavChatList } from "./workspace-nav-chat-list";
import { WorkspaceNavMenu } from "./workspace-nav-menu";
import { WorkspaceSelector } from "./workspace-selector";
import { WorkspaceSidebarNavigation } from "./workspace-sidebar-navigation";

import styles from "./workspace-sidebar.module.css";

export function WorkspaceSidebar({
  ...props
}: React.ComponentProps<typeof Sidebar>) {
  const { setOpenMobile } = useSidebar();
  const isSidebarOpen = useSidebarExpanded();
  const { motionOn } = useWorkspaceAppearance();
  // A client sees chats and nothing internal: no workspace switcher, plugin
  // pages, channels, projects or background work.
  const isClient = useIsClient();
  // Until the role resolves the user may be a client: show no internal UI.
  const unresolved = useIsRoleUnresolved();
  const showInternal = !isClient && !unresolved;

  const closeMobileSidebarForWorkspaceLink: React.MouseEventHandler<
    HTMLDivElement
  > = (event) => {
    if (
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return;
    }

    const target = event.target;
    if (!(target instanceof Element)) return;

    const link = target.closest<HTMLAnchorElement>("a[href]");
    if (!link || link.hasAttribute("download")) return;
    if (link.target && link.target !== "_self") return;

    const url = new URL(link.href, window.location.href);
    if (url.origin !== window.location.origin) return;
    if (
      url.pathname !== "/workspace" &&
      !url.pathname.startsWith("/workspace/")
    ) {
      return;
    }

    setOpenMobile(false);
  };

  return (
    <ThreadDeleteDialogProvider>
      <WorkspaceSidebarNavigation />
      <Sidebar variant="sidebar" collapsible="icon" {...props}>
        <SidebarHeader
          className={cn("py-0", styles.phoneTargets)}
          onClickCapture={closeMobileSidebarForWorkspaceLink}
        >
          <WorkspaceHeader />
          {isSidebarOpen && showInternal && <WorkspaceSelector />}
        </SidebarHeader>
        <SidebarContent
          className={styles.phoneTargets}
          onClickCapture={closeMobileSidebarForWorkspaceLink}
        >
          <WorkspaceNavChatList />
          {showInternal && <PluginNavigation />}
          {showInternal && <WorkspaceChannelsList />}
          {isSidebarOpen && (
            <>
              {showInternal && <ProjectsSection />}
              <RecentChatList />
            </>
          )}
        </SidebarContent>
        <SidebarFooter
          className={styles.phoneTargets}
          onClickCapture={closeMobileSidebarForWorkspaceLink}
        >
          {/* Docked, not floating: it used to cover the composer and lists. */}
          {isSidebarOpen && (
            <Scraps
              names={["compass", "twine", "sunflowers"]}
              live={motionOn}
              size={52}
              className={styles.scraps}
            />
          )}
          {!isClient && <BackgroundJobs />}
          <WorkspaceNavMenu />
          {/* The maker's signature, at the far end from the MomoBot name. */}
          {isSidebarOpen && (
            <div className={styles.signature}>
              <BrandSignature />
            </div>
          )}
        </SidebarFooter>
        <SidebarRail />
      </Sidebar>
    </ThreadDeleteDialogProvider>
  );
}
