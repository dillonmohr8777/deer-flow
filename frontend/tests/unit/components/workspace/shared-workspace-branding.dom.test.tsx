import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { SharedWorkspaceBranding } from "@/components/workspace/command-center/shared-workspace-branding";
import {
  WorkspaceBrandingError,
  type WorkspaceBranding,
} from "@/core/workspaces/api";

const saved: WorkspaceBranding = {
  workspace_id: "team-a",
  workspace_name: "Team A",
  brand_name: "Saved brand",
  logo: null,
  treatment: "current",
  version: 1,
  updated_at: null,
  can_edit: true,
};
function fixture(canEdit = true) {
  return {
    workspaceId: "team-a",
    branding: {
      data: { ...saved, can_edit: canEdit },
      isPending: false,
      isFetching: false,
      error: null as Error | null,
      refetch: rs.fn(),
    },
    save: { mutateAsync: rs.fn(), isPending: false },
    reset: { mutateAsync: rs.fn(), isPending: false },
  };
}
type Shared = Parameters<typeof SharedWorkspaceBranding>[0]["shared"];
afterEach(() => {
  cleanup();
});

describe("shared brand editor", () => {
  it("renders member branding without offering shared mutations", () => {
    const shared = fixture(false);
    render(<SharedWorkspaceBranding shared={shared as unknown as Shared} />);
    expect(
      screen.getByLabelText<HTMLInputElement>("Workspace brand name").disabled,
    ).toBe(true);
    expect(
      screen.queryByRole("button", { name: "Save shared brand" }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Reset shared brand" }),
    ).toBeNull();
    expect(shared.save.mutateAsync).not.toHaveBeenCalled();
  });
  it("enforces code-point limits, preserves drafts on refresh errors and 412, and requires an explicit latest-version reload", async () => {
    const shared = fixture();
    shared.save.mutateAsync.mockRejectedValue(
      new WorkspaceBrandingError(412, "A teammate changed this brand."),
    );
    const view = render(
      <SharedWorkspaceBranding shared={shared as unknown as Shared} />,
    );
    const name = screen.getByLabelText<HTMLInputElement>(
      "Workspace brand name",
    );
    fireEvent.change(name, { target: { value: "🦌".repeat(121) } });
    expect(
      screen.getByRole<HTMLButtonElement>("button", {
        name: "Save shared brand",
      }).disabled,
    ).toBe(true);
    fireEvent.change(name, { target: { value: "🦌".repeat(120) } });
    shared.branding.error = new Error("Offline");
    view.rerender(
      <SharedWorkspaceBranding shared={shared as unknown as Shared} />,
    );
    expect(name.value).toBe("🦌".repeat(120));
    fireEvent.click(screen.getByRole("button", { name: "Save shared brand" }));
    await waitFor(() =>
      expect(screen.getByText("A teammate changed this brand.")).toBeTruthy(),
    );
    expect(name.value).toBe("🦌".repeat(120));
    expect(shared.save.mutateAsync).toHaveBeenCalledWith({
      draft: { brand_name: "🦌".repeat(120), logo: null, treatment: "current" },
      version: 1,
    });
    expect(
      screen.getByRole<HTMLButtonElement>("button", {
        name: "Save shared brand",
      }).disabled,
    ).toBe(true);
    shared.branding.refetch.mockImplementation(() => {
      shared.branding.data = {
        ...saved,
        brand_name: "Teammate brand",
        version: 2,
      };
      shared.branding.error = null;
      return Promise.resolve({ data: shared.branding.data });
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Discard draft & load latest" }),
    );
    await waitFor(() => expect(name.value).toBe("Teammate brand"));
    expect(
      screen.getByText(
        "Latest shared branding loaded. You can edit this version.",
      ),
    ).toBeTruthy();
  });
});
