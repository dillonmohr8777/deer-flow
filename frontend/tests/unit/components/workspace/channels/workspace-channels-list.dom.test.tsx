import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

const state = rs.hoisted(() => ({
  connect: rs.fn(),
  configure: rs.fn(),
  selectWorkspace: rs.fn(),
  workspaceId: "momentum" as string | null,
  workspaceLoaded: true,
  connectionStatus: "not_connected",
}));

rs.mock("@/components/ui/sidebar", () => ({
  useSidebar: () => ({ open: true }),
  SidebarGroup: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  SidebarGroupLabel: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  SidebarMenu: ({ children }: { children: React.ReactNode }) => (
    <ul>{children}</ul>
  ),
  SidebarMenuItem: ({ children }: { children: React.ReactNode }) => (
    <li>{children}</li>
  ),
}));
rs.mock("@/core/channels/hooks", () => ({
  useChannelProviders: () => ({
    enabled: true,
    isLoading: false,
    error: null,
    providers: [
      {
        provider: "slack",
        display_name: "Slack",
        enabled: true,
        configured: true,
        connectable: true,
        auth_mode: "binding_code",
        connection_status: state.connectionStatus,
        credential_fields: [],
      },
    ],
  }),
  useConnectChannelProvider: () => ({
    mutateAsync: state.connect,
    isPending: false,
  }),
  useConfigureChannelProvider: () => ({
    mutateAsync: state.configure,
    isPending: false,
  }),
}));
rs.mock("@/core/workspaces/hooks", () => ({
  useWorkspaceSelection: () => ({
    data: state.workspaceLoaded
      ? { active_workspace_id: state.workspaceId, workspaces: [] }
      : undefined,
    busy: false,
    isLoading: !state.workspaceLoaded,
    error: null,
    selectWorkspace: state.selectWorkspace,
  }),
}));
rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      sidebar: { channels: "Channels" },
      channels: {
        connected: "Connected",
        connect: "Connect",
        unavailable: "Unavailable",
      },
    },
  }),
}));
rs.mock(
  "@/components/workspace/channels/channel-runtime-config-dialog",
  () => ({
    ChannelRuntimeConfigDialog: () => null,
  }),
);

import { WorkspaceChannelsList } from "@/components/workspace/channels/workspace-channels-list";

beforeEach(() => {
  state.workspaceId = "momentum";
  state.workspaceLoaded = true;
  state.connectionStatus = "not_connected";
  state.selectWorkspace.mockResolvedValue(undefined);
  state.connect.mockResolvedValue({
    instruction: "Connect in Slack",
    expires_in: 60,
  });
});
afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

test("shared workspace opens personal setup without submitting a channel mutation", async () => {
  render(<WorkspaceChannelsList />);
  fireEvent.click(screen.getByRole("button", { name: "Manage" }));
  await waitFor(() => expect(state.selectWorkspace).toHaveBeenCalledWith(null));
  expect(state.connect).not.toHaveBeenCalled();
  expect(state.configure).not.toHaveBeenCalled();
  expect(
    screen.getByText("Channel connections use your private workspace."),
  ).toBeTruthy();
});

test("private workspace keeps the working connect flow", async () => {
  state.workspaceId = null;
  render(<WorkspaceChannelsList />);
  fireEvent.click(screen.getByRole("button", { name: "Connect" }));
  await waitFor(() => expect(state.connect).toHaveBeenCalledWith("slack"));
  expect(state.selectWorkspace).not.toHaveBeenCalled();
});

test("private connected state remains visible", () => {
  state.workspaceId = null;
  state.connectionStatus = "connected";
  render(<WorkspaceChannelsList />);
  expect(screen.getByRole("button", { name: "Connected" })).toBeTruthy();
});

test("unresolved workspace cannot submit setup to an unknown scope", () => {
  state.workspaceLoaded = false;
  render(<WorkspaceChannelsList />);
  expect(screen.queryByRole("button")).toBeNull();
  expect(state.connect).not.toHaveBeenCalled();
});
