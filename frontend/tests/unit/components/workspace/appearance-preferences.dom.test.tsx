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
      <button
        onClick={() => appearance.update({ treatment: "current", motion: true })}
      >
        Current
      </button>
      <button onClick={() => appearance.update({ treatment: "space" })}>
        Space
      </button>
      <button onClick={appearance.reset}>Reset</button>
    </>
  );
}

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  userId = "account-a";
  rs.restoreAllMocks();
});

describe("workspace appearance", () => {
  it("validates browser data, persists only to the current account, resets, and pauses decorative motion", async () => {
    expect(
      parseAppearance(
        '{"treatment":"unknown","motion":"true","logo":"https://example.com/a.svg"}',
      ),
    ).toEqual(DEFAULT_APPEARANCE);
    expect(parseAppearance("broken")).toEqual(DEFAULT_APPEARANCE);
    expect(DEFAULT_APPEARANCE.treatment).toBe("paper");
    for (const saved of [
      "current",
      "classic",
      "paper",
      "space",
      "future",
      "retro",
    ] as const)
      expect(
        parseAppearance(JSON.stringify({ treatment: saved })).treatment,
      ).toBe(saved);
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
    // Paper is the default; "current" stays selectable and is saved.
    expect(screen.getByTestId("preference").textContent).toBe("paper");
    fireEvent.click(screen.getByText("Current"));
    expect(
      parseAppearance(window.localStorage.getItem(appearanceKey("account-a")))
        .treatment,
    ).toBe("current");

    userId = "account-b";
    view.rerender(
      <WorkspaceAppearanceProvider>
        <Controls />
      </WorkspaceAppearanceProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("preference").textContent).toBe("paper"),
    );
    expect(window.localStorage.getItem(appearanceKey("account-b"))).toBeNull();
    userId = "account-a";
    view.rerender(
      <WorkspaceAppearanceProvider>
        <Controls />
      </WorkspaceAppearanceProvider>,
    );
    // The saved choice is respected over the new default.
    await waitFor(() =>
      expect(screen.getByTestId("preference").textContent).toBe("current"),
    );

    // A new treatment (space/future/retro) persists exactly like the
    // existing ones.
    fireEvent.click(screen.getByText("Space"));
    expect(screen.getByTestId("preference").textContent).toBe("space");
    expect(
      parseAppearance(window.localStorage.getItem(appearanceKey("account-a")))
        .treatment,
    ).toBe("space");

    fireEvent.click(screen.getByText("Reset"));
    expect(window.localStorage.getItem(appearanceKey("account-a"))).toBeNull();
    expect(screen.getByTestId("preference").textContent).toBe("paper");

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
