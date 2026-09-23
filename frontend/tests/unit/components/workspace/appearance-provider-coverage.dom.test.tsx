import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import {
  useWorkspaceAppearance,
  WorkspaceAppearanceProvider,
} from "@/components/workspace/command-center/appearance-provider";

// Coverage fix: data-treatment was only ever set on the Command Center
// .root, so sidebar/header/threads stayed on the "current" palette while
// the dashboard alone went cream. WorkspaceAppearanceProvider now wraps
// its children in one element carrying data-treatment, so anything mounted
// under the provider - not just Command Center - can see it.
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "account-a" } }),
}));

function SetCurrent() {
  const appearance = useWorkspaceAppearance();
  return (
    <button onClick={() => appearance.update({ treatment: "current" })}>
      Current
    </button>
  );
}

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  rs.restoreAllMocks();
});

describe("WorkspaceAppearanceProvider coverage", () => {
  it("sets data-treatment on the element wrapping the whole workspace, not just Command Center", async () => {
    const { container, unmount } = render(
      <WorkspaceAppearanceProvider>
        <SetCurrent />
        <div data-testid="rest-of-workspace">sidebar + header + threads</div>
      </WorkspaceAppearanceProvider>,
    );

    const wrapper = container.querySelector("[data-treatment]");
    expect(wrapper).toBeTruthy();
    expect(wrapper?.getAttribute("data-treatment")).toBe("paper");
    expect(wrapper?.hasAttribute("data-workspace-shell")).toBe(true);
    expect(wrapper?.contains(screen.getByTestId("rest-of-workspace"))).toBe(
      true,
    );
    // Mirrored onto <html> so portalled dialogs, menus and the mobile
    // sidebar sheet get the same skin.
    expect(document.documentElement.dataset.treatment).toBe("paper");

    fireEvent.click(screen.getByText("Current"));
    await waitFor(() =>
      expect(
        container
          .querySelector("[data-treatment]")
          ?.getAttribute("data-treatment"),
      ).toBe("current"),
    );
    expect(document.documentElement.dataset.treatment).toBe("current");

    // Leaving the workspace (landing, login) takes the skin with it.
    unmount();
    expect(document.documentElement.dataset.treatment).toBeUndefined();
  });

  it("mirrors data-motion (brandMotionAllowed) onto the wrapper and <html> the same way", async () => {
    // Default preferences have motion off, so both should read "off" — the
    // gate future's H1 echo and retro's resolve read directly.
    const { container, unmount } = render(
      <WorkspaceAppearanceProvider>
        <div data-testid="rest-of-workspace">sidebar + header + threads</div>
      </WorkspaceAppearanceProvider>,
    );
    const wrapper = container.querySelector("[data-treatment]");
    await waitFor(() =>
      expect(wrapper?.getAttribute("data-motion")).toBe("off"),
    );
    expect(document.documentElement.dataset.motion).toBe("off");

    unmount();
    expect(document.documentElement.dataset.motion).toBeUndefined();
  });
});
