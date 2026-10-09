import { cookies } from "next/headers";
import { Toaster } from "sonner";

import { QueryClientProvider } from "@/components/query-client-provider";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { WorkspaceAppearanceProvider } from "@/components/workspace/command-center/appearance-provider";
import { RetroResolve } from "@/components/workspace/command-center/retro-resolve";
import { CommandPalette } from "@/components/workspace/command-palette";
import { ExperienceModeChooser } from "@/components/workspace/experience-mode-chooser";
import { GatewayOfflineBanner } from "@/components/workspace/gateway-offline-banner";
import { ModelLoadErrorBanner } from "@/components/workspace/model-load-error-banner";
import { SettingsDialogHost } from "@/components/workspace/settings";
import {
  SkipToContent,
  WORKSPACE_MAIN_CONTENT_ID,
  WORKSPACE_MAIN_ID,
} from "@/components/workspace/skip-to-content";
import { WorkspaceSettingsDeepLink } from "@/components/workspace/workspace-settings-deep-link";
import { WorkspaceSidebar } from "@/components/workspace/workspace-sidebar";
import { ExtensionPageBootstrap } from "@/core/extensions/hooks";
import { UserPreferencesBoundary } from "@/core/settings/user-preferences-boundary";

function parseSidebarOpenCookie(
  value: string | undefined,
): boolean | undefined {
  if (value === "true") return true;
  if (value === "false") return false;
  return undefined;
}

export async function WorkspaceContent({
  children,
  gatewayUnavailable = false,
}: Readonly<{
  children: React.ReactNode;
  gatewayUnavailable?: boolean;
}>) {
  const cookieStore = await cookies();
  const initialSidebarOpen = parseSidebarOpenCookie(
    cookieStore.get("sidebar_state")?.value,
  );

  return (
    <QueryClientProvider>
      <UserPreferencesBoundary>
        <ExtensionPageBootstrap />
        <WorkspaceAppearanceProvider>
          <SidebarProvider
            className="h-screen"
            defaultOpen={initialSidebarOpen}
          >
            <SkipToContent />
            <WorkspaceSidebar />
            <SidebarInset
              id={WORKSPACE_MAIN_ID}
              tabIndex={-1}
              className="min-w-0 focus:outline-none"
              style={{ width: "auto" }}
            >
              {/* Always-present target for RetroResolve's pixelation filter
                  (retro-resolve.tsx). React owns this node and everything
                  inside it for the lifetime of the app, so an imperative
                  effect can safely set a style property on it without ever
                  restructuring its children — see that file for why an
                  effect-created, moved-and-restored wrapper crashed React's
                  own reconciliation of this same content. The inline flex
                  styles mirror #workspace-main's own so this extra layer is
                  invisible to layout. */}
              <div
                id={WORKSPACE_MAIN_CONTENT_ID}
                className="min-h-0 w-full min-w-0 flex-col"
                style={{ display: "flex", flex: "1 1 auto" }}
              >
                <GatewayOfflineBanner gatewayUnavailable={gatewayUnavailable} />
                <ModelLoadErrorBanner gatewayUnavailable={gatewayUnavailable} />
                {children}
              </div>
            </SidebarInset>
          </SidebarProvider>
          <RetroResolve />
          <CommandPalette />
          <SettingsDialogHost />
          <ExperienceModeChooser />
          <WorkspaceSettingsDeepLink />
          <Toaster position="top-center" />
        </WorkspaceAppearanceProvider>
      </UserPreferencesBoundary>
    </QueryClientProvider>
  );
}
