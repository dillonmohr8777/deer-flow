import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

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

function SetPaper() {
  const appearance = useWorkspaceAppearance();
  return (
    <button onClick={() => appearance.update({ treatment: "paper" })}>
      Paper
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
    const { container } = render(
      <WorkspaceAppearanceProvider>
        <SetPaper />
        <div data-testid="rest-of-workspace">sidebar + header + threads</div>
      </WorkspaceAppearanceProvider>,
    );

    const wrapper = container.querySelector("[data-treatment]");
    expect(wrapper).toBeTruthy();
    expect(wrapper?.getAttribute("data-treatment")).toBe("current");
    expect(wrapper?.contains(screen.getByTestId("rest-of-workspace"))).toBe(
      true,
    );

    fireEvent.click(screen.getByText("Paper"));
    await waitFor(() =>
      expect(
        container.querySelector("[data-treatment]")?.getAttribute(
          "data-treatment",
        ),
      ).toBe("paper"),
    );
  });
});
