"use client";

import {
  Sidebar,
  SidebarHeader,
  SidebarContent,
  SidebarFooter,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";

import { WorkspaceChannelsList } from "./channels/workspace-channels-list";
import { BackgroundJobs } from "./command-center/background-jobs";
import { PluginNavigation } from "./plugin-navigation";
import { ProjectsSection } from "./projects-section";
import { RecentChatList } from "./recent-chat-list";
import { ThreadDeleteDialogProvider } from "./thread-delete-dialog";
import { WorkspaceHeader } from "./workspace-header";
import { WorkspaceNavChatList } from "./workspace-nav-chat-list";
import { WorkspaceNavMenu } from "./workspace-nav-menu";
import { WorkspaceSelector } from "./workspace-selector";

export function WorkspaceSidebar({
  ...props
}: React.ComponentProps<typeof Sidebar>) {
  const { open: isSidebarOpen } = useSidebar();
  return (
    <ThreadDeleteDialogProvider>
      <Sidebar variant="sidebar" collapsible="icon" {...props}>
        <SidebarHeader className="py-0">
          <WorkspaceHeader />
          {isSidebarOpen && <WorkspaceSelector />}
        </SidebarHeader>
        <SidebarContent>
          <WorkspaceNavChatList />
          <PluginNavigation />
          <WorkspaceChannelsList />
          {isSidebarOpen && (
            <>
              <ProjectsSection />
              <RecentChatList />
            </>
          )}
        </SidebarContent>
        <SidebarFooter>
          {/* Docked, not floating: it used to cover the composer and lists. */}
          <BackgroundJobs />
          <WorkspaceNavMenu />
        </SidebarFooter>
        <SidebarRail />
      </Sidebar>
    </ThreadDeleteDialogProvider>
  );
}
