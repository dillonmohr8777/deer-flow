import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { StrictMode } from "react";

import {
  getSettingsDialogSnapshot,
  openSettingsDialog,
  setSettingsDialogOpen,
  useSettingsDialog,
} from "@/components/workspace/settings/settings-dialog-store";
import { SubagentSettingsPage } from "@/components/workspace/settings/subagent-settings-page";
import { WorkspaceSettingsDeepLink } from "@/components/workspace/workspace-settings-deep-link";
import { enUS } from "@/core/i18n/locales/en-US";
import type { Subagent } from "@/core/subagents";

const fixture = rs.hoisted(() => ({
  search: new URLSearchParams(),
  router: { replace: rs.fn() },
  role: "admin",
  subagents: [] as Subagent[],
  mutateAsync: rs.fn(),
}));

rs.mock("next/navigation", () => ({
  usePathname: () => "/workspace/command-center",
  useSearchParams: () => fixture.search,
  useRouter: () => fixture.router,
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { system_role: fixture.role } }),
}));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));
rs.mock("@/core/models/hooks", () => ({ useModels: () => ({ models: [] }) }));
rs.mock("@/core/subagents", () => ({
  useSubagents: () => ({ subagents: fixture.subagents, isLoading: false }),
  useCreateManagedSubagent: () => ({ mutateAsync: fixture.mutateAsync }),
  useUpdateManagedSubagent: () => ({ mutateAsync: fixture.mutateAsync }),
  useDeleteManagedSubagent: () => ({ mutateAsync: fixture.mutateAsync }),
}));

const scout: Subagent = {
  name: "scout",
  display_name: "Scout",
  description: "Research the source material.",
  system_prompt: "Preserve the original research brief.",
  tools: ["read_file"],
  disallowed_tools: ["execute"],
  skills: [],
  model: "inherit",
  max_turns: 12,
  timeout_seconds: 300,
  enabled: true,
  source: "managed",
  editable: true,
  conflict: false,
  config_overrides: {},
};

function Harness({ pageReady = true }: { pageReady?: boolean }) {
  const { open, section } = useSettingsDialog();
  return (
    <StrictMode>
      <WorkspaceSettingsDeepLink />
      {open && section === "subagents" && pageReady && <SubagentSettingsPage />}
    </StrictMode>
  );
}

beforeEach(() => {
  fixture.search = new URLSearchParams();
  fixture.router.replace.mockClear();
  fixture.mutateAsync.mockClear();
  fixture.subagents = [scout];
  fixture.role = "admin";
  setSettingsDialogOpen(false);
});

afterEach(() => {
  cleanup();
  setSettingsDialogOpen(false);
});

test("retains a specialist deep link until the lazy page and catalog arrive, then clears it only on Settings close", () => {
  fixture.search = new URLSearchParams(
    "settings=subagents&specialist=scout&view=agents",
  );
  fixture.subagents = [];
  const view = render(<Harness pageReady={false} />);

  expect(getSettingsDialogSnapshot()).toEqual({
    open: true,
    section: "subagents",
  });
  expect(fixture.router.replace).not.toHaveBeenCalled();

  view.rerender(<Harness />);
  expect(screen.queryByRole("dialog")).toBeNull();
  fixture.subagents = [scout];
  view.rerender(<Harness />);
  expect(
    screen.getByRole("dialog", { name: "Edit managed subagent" }),
  ).toBeTruthy();
  expect(screen.getByLabelText("Display name")).toHaveProperty(
    "value",
    "Scout",
  );

  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(fixture.router.replace).not.toHaveBeenCalled();
  expect(fixture.mutateAsync).not.toHaveBeenCalled();

  act(() => setSettingsDialogOpen(false));
  expect(fixture.router.replace).toHaveBeenCalledExactlyOnceWith(
    "/workspace/command-center?view=agents",
    { scroll: false },
  );
  expect(getSettingsDialogSnapshot().open).toBe(false);
});

test("a different specialist query opens its actual editor while Settings stays mounted", () => {
  fixture.search = new URLSearchParams("settings=subagents&specialist=scout");
  fixture.subagents = [
    scout,
    { ...scout, name: "anchor", display_name: "Anchor" },
  ];
  const view = render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

  fixture.search = new URLSearchParams("settings=subagents&specialist=anchor");
  view.rerender(<Harness />);
  expect(
    screen.getByRole("dialog", { name: "Edit managed subagent" }),
  ).toBeTruthy();
  expect(screen.getByLabelText("Display name")).toHaveProperty(
    "value",
    "Anchor",
  );
  expect(fixture.router.replace).not.toHaveBeenCalled();
});

test("other settings deep links retain their section and unrelated query parameters", () => {
  fixture.search = new URLSearchParams("settings=notification&view=agents");
  render(<Harness />);
  expect(getSettingsDialogSnapshot()).toEqual({
    open: true,
    section: "notification",
  });
  expect(fixture.router.replace).not.toHaveBeenCalled();
  act(() => setSettingsDialogOpen(false));
  expect(fixture.router.replace).toHaveBeenCalledExactlyOnceWith(
    "/workspace/command-center?view=agents",
    { scroll: false },
  );
});

test("menu and palette store actions leave non-settings URLs alone", () => {
  fixture.search = new URLSearchParams("settings=unknown&view=agents");
  render(<Harness />);
  expect(getSettingsDialogSnapshot().open).toBe(false);
  act(() => openSettingsDialog("appearance"));
  expect(getSettingsDialogSnapshot()).toEqual({
    open: true,
    section: "appearance",
  });
  act(() => openSettingsDialog("about"));
  expect(getSettingsDialogSnapshot().section).toBe("about");
  act(() => setSettingsDialogOpen(false));
  expect(fixture.router.replace).not.toHaveBeenCalled();
});

test("a query cannot open a managed editor without admin and editable conflict-free capability", () => {
  fixture.search = new URLSearchParams("settings=subagents&specialist=scout");
  fixture.role = "user";
  const view = render(<Harness />);
  expect(screen.queryByRole("dialog")).toBeNull();
  fixture.role = "admin";
  fixture.subagents = [{ ...scout, editable: false }];
  view.rerender(<Harness />);
  expect(screen.queryByRole("dialog")).toBeNull();
  fixture.subagents = [{ ...scout, conflict: true }];
  view.rerender(<Harness />);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(fixture.mutateAsync).not.toHaveBeenCalled();
});
