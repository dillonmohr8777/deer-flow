import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import {
  appearanceKey,
  brandMotionAllowed,
  DEFAULT_APPEARANCE,
  parseAppearance,
} from "@/components/workspace/command-center/appearance-preferences";
import {
  useWorkspaceAppearance,
  WorkspaceAppearanceProvider,
} from "@/components/workspace/command-center/appearance-provider";

let userId = "account-a";
let sharedName: string | null = null;
let scopeKnown = true;
rs.mock("@/core/workspaces/hooks", () => ({
  useWorkspaceBranding: () => ({
    workspaces: { isSuccess: scopeKnown },
    workspaceId: sharedName ? "shared-a" : null,
    workspace: sharedName ? { name: "Workspace A" } : undefined,
    branding: {
      data: sharedName
        ? { brand_name: sharedName, logo: null, treatment: "paper" }
        : undefined,
    },
  }),
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: userId } }),
}));

function Controls() {
  const appearance = useWorkspaceAppearance();
  return (
    <>
      <output data-testid="preference">
        {appearance.preferences.treatment}
      </output>
      <output data-testid="persistence">{appearance.persistence}</output>
      <output data-testid="label">{appearance.preferences.label}</output>
      <output data-testid="motion">
        {String(appearance.preferences.motion)}
      </output>
      <button
        onClick={() =>
          appearance.update({
            treatment: "classic",
            followWorkspaceStyle: false,
          })
        }
      >
        Personal style
      </button>
      <button onClick={() => appearance.update({ followWorkspaceStyle: true })}>
        Follow workspace
      </button>
      <button
        onClick={() => appearance.update({ treatment: "paper", motion: true })}
      >
        Paper
      </button>
      <button onClick={appearance.reset}>Reset</button>
    </>
  );
}

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  userId = "account-a";
  sharedName = null;
  scopeKnown = true;
  rs.restoreAllMocks();
});

describe("workspace appearance", () => {
  it("shows the shared identity while preserving personal style and motion, and hides private brands until scope is known", async () => {
    window.localStorage.setItem(
      appearanceKey(userId),
      JSON.stringify({
        label: "Private client",
        treatment: "classic",
        motion: true,
      }),
    );
    sharedName = "Team brand";
    const view = render(
      <WorkspaceAppearanceProvider>
        <Controls />
      </WorkspaceAppearanceProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("label").textContent).toBe("Team brand"),
    );
    expect(screen.getByTestId("preference").textContent).toBe("classic");
    expect(screen.getByTestId("motion").textContent).toBe("true");
    fireEvent.click(screen.getByText("Follow workspace"));
    expect(screen.getByTestId("preference").textContent).toBe("paper");
    fireEvent.click(screen.getByText("Personal style"));
    expect(screen.getByTestId("preference").textContent).toBe("classic");
    expect(
      parseAppearance(window.localStorage.getItem(appearanceKey(userId))).label,
    ).toBe("Private client");
    sharedName = null;
    scopeKnown = false;
    view.rerender(
      <WorkspaceAppearanceProvider>
        <Controls />
      </WorkspaceAppearanceProvider>,
    );
    expect(screen.getByTestId("label").textContent).toBe("");
    scopeKnown = true;
    view.rerender(
      <WorkspaceAppearanceProvider>
        <Controls />
      </WorkspaceAppearanceProvider>,
    );
    expect(screen.getByTestId("label").textContent).toBe("Private client");
  });
  it("validates browser data, persists only to the current account, resets, and pauses decorative motion", async () => {
    expect(
      parseAppearance(
        '{"treatment":"unknown","motion":"true","logo":"https://example.com/a.svg"}',
      ),
    ).toEqual(DEFAULT_APPEARANCE);
    expect(parseAppearance("broken")).toEqual(DEFAULT_APPEARANCE);
    expect(
      parseAppearance(JSON.stringify({ label: "x".repeat(200) })).label,
    ).toHaveLength(40);
    expect(appearanceKey("a:b")).not.toBe(appearanceKey("a%3Ab"));

    const view = render(
      <WorkspaceAppearanceProvider>
        <Controls />
      </WorkspaceAppearanceProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("persistence").textContent).toBe("local"),
    );
    fireEvent.click(screen.getByText("Paper"));
    expect(
      parseAppearance(window.localStorage.getItem(appearanceKey("account-a")))
        .treatment,
    ).toBe("paper");

    userId = "account-b";
    view.rerender(
      <WorkspaceAppearanceProvider>
        <Controls />
      </WorkspaceAppearanceProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("preference").textContent).toBe("current"),
    );
    expect(window.localStorage.getItem(appearanceKey("account-b"))).toBeNull();
    userId = "account-a";
    view.rerender(
      <WorkspaceAppearanceProvider>
        <Controls />
      </WorkspaceAppearanceProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("preference").textContent).toBe("paper"),
    );
    fireEvent.click(screen.getByText("Reset"));
    expect(window.localStorage.getItem(appearanceKey("account-a"))).toBeNull();
    expect(screen.getByTestId("preference").textContent).toBe("current");

    const enabled = {
      motion: true,
      reducedMotion: false,
      visible: true,
      inView: true,
    };
    expect(brandMotionAllowed(enabled)).toBe(true);
    for (const condition of [
      { motion: false },
      { reducedMotion: true },
      { visible: false },
      { inView: false },
    ])
      expect(brandMotionAllowed({ ...enabled, ...condition })).toBe(false);

    act(() => {
      window.localStorage.setItem(
        appearanceKey("account-a"),
        '{"treatment":"classic"}',
      );
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: appearanceKey("account-a"),
          storageArea: window.localStorage,
        }),
      );
    });
    expect(screen.getByTestId("preference").textContent).toBe("classic");
  });
});
