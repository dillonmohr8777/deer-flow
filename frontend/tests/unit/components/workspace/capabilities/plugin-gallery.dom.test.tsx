import { afterEach, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen, within } from "@testing-library/react";
import type { PropsWithChildren } from "react";

const mocks = rs.hoisted(() => ({
  role: "user",
  definitions: [] as unknown[],
  items: {} as Record<string, unknown[]>,
}));

rs.mock("next/navigation", () => ({
  usePathname: () => "/workspace/capabilities",
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

rs.mock("@tanstack/react-query", () => ({
  useQueries: ({ queries }: { queries: { queryKey: string[] }[] }) =>
    queries.map((query) => ({
      data: { items: mocks.items[query.queryKey[0]!] ?? [] },
      isError: false,
    })),
  useQueryClient: () => ({ invalidateQueries: rs.fn() }),
}));

rs.mock("@/core/capabilities/hooks", () => ({
  useCapabilityCatalog: () => ({
    data: mocks.definitions,
    isError: false,
    isLoading: false,
  }),
  installationQuery: (adapter: string) => ({ queryKey: [adapter] }),
}));

rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { system_role: mocks.role } }),
}));

rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: () => false }));

rs.mock("@/components/workspace/capabilities/plugin-icon", () => ({
  PluginIcon: () => null,
}));

rs.mock("@/components/workspace/capabilities/plugin-adapters", () => ({
  pluginSettingsAdapters: {},
}));

// The administrator path hands its catalog rows to the MCP manager; render
// them through the real directory so the connected split is what is tested.
rs.mock("@/components/workspace/capabilities/mcp-plugin-manager", () => ({
  MCPPluginManager: ({ catalog }: { catalog: PluginDirectoryEntry[] }) => (
    <PluginDirectory entries={catalog} />
  ),
}));

import {
  PluginDirectory,
  type PluginDirectoryEntry,
} from "@/components/workspace/capabilities/plugin-directory";
import { PluginGallery } from "@/components/workspace/capabilities/plugin-gallery";
import { I18nProvider } from "@/core/i18n/context";

function Wrapper({ children }: PropsWithChildren) {
  return <I18nProvider initialLocale="en-US">{children}</I18nProvider>;
}

function manifest(id: string, adapter: string) {
  return {
    id,
    adapter,
    category: "business",
    name: { "en-US": id },
    description: { "en-US": `${id} tools` },
    setup: { "en-US": "" },
    aliases: [],
    icon: null,
  };
}

function installation(
  plugin_id: string,
  adapter: string,
  extra: Record<string, unknown>,
) {
  return {
    id: `install-${plugin_id}`,
    plugin_id,
    adapter,
    name: plugin_id,
    description: `${plugin_id} tools`,
    installed: true,
    enabled: true,
    auth_status: "configured",
    ...extra,
  };
}

afterEach(() => {
  cleanup();
  mocks.role = "user";
  mocks.definitions = [];
  mocks.items = {};
});

function connectedNames() {
  const sheet = screen.queryByTestId("plugin-connected");
  if (!sheet) return [];
  return within(sheet)
    .getAllByRole("article")
    .map((row) => within(row).getByRole("heading").textContent);
}

it("keeps an install that still needs an account out of Connected", () => {
  mocks.role = "admin";
  mocks.definitions = [
    manifest("hubspot", "business"),
    manifest("dingtalk", "business"),
  ];
  mocks.items = {
    business: [
      installation("hubspot", "business", { auth_status: "required" }),
      installation("dingtalk", "business", { auth_status: "configured" }),
    ],
  };
  render(<PluginGallery query="" />, { wrapper: Wrapper });
  expect(connectedNames()).toEqual(["dingtalk"]);
  const hubspot = screen
    .getAllByRole("article")
    .find((row) => row.textContent?.includes("hubspot"))!;
  expect(within(hubspot).getByText("Account required")).toBeDefined();
  expect(
    within(hubspot).getByRole("button", { name: "Connect hubspot" }),
  ).toBeDefined();
});

it("keeps switched-off, unselectable and unauthorized MCP tools out of Connected for members", () => {
  mocks.definitions = [
    manifest("github", "mcp"),
    manifest("notion", "mcp"),
    manifest("postgres", "mcp"),
    manifest("jira", "mcp"),
  ];
  mocks.items = {
    mcp: [
      installation("github", "mcp", { auth_status: "connected" }),
      installation("notion", "mcp", { auth_status: "required" }),
      installation("postgres", "mcp", { enabled: false }),
      installation("jira", "mcp", { selectable: false }),
    ],
  };
  render(<PluginGallery query="" />, { wrapper: Wrapper });
  expect(connectedNames()).toEqual(["github"]);
  expect(screen.getAllByRole("article")).toHaveLength(4);
});

it("does not promise a switch in the Connected hint", () => {
  mocks.definitions = [manifest("github", "mcp")];
  mocks.items = { mcp: [installation("github", "mcp", {})] };
  render(<PluginGallery query="" />, { wrapper: Wrapper });
  expect(screen.queryByText(/switch/i)).toBeNull();
});
