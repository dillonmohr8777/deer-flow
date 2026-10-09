import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { act, cleanup, render } from "@testing-library/react";
import { useState } from "react";

import { type BrandTreatment } from "@/components/workspace/command-center/appearance-preferences";
import { RetroResolve } from "@/components/workspace/command-center/retro-resolve";
import { WORKSPACE_MAIN_CONTENT_ID } from "@/components/workspace/skip-to-content";

const appearance = rs.hoisted(() => ({
  value: {
    preferences: {
      treatment: "retro" as BrandTreatment,
      motion: true,
      logo: null as string | null,
      label: "",
    },
    motionOn: true,
  },
}));

rs.mock("@/components/workspace/command-center/appearance-provider", () => ({
  useWorkspaceAppearance: () => appearance.value,
}));

rs.mock("next/navigation", () => ({
  usePathname: () => "/workspace/command-center",
}));

const WRAPPER_SELECTOR = "[data-retro-resolve-wrapper]";

let target: HTMLElement;
let content: HTMLElement;

beforeEach(() => {
  // Mirrors WorkspaceContent: a persistent, React-owned div is already in
  // the DOM before RetroResolve's effect ever runs — it is never created or
  // moved by that effect, only styled.
  target = document.createElement("div");
  target.id = WORKSPACE_MAIN_CONTENT_ID;
  // A marker child so we can prove content is never lost, duplicated, or
  // reparented, only filtered.
  content = document.createElement("h1");
  content.textContent = "Mission Control";
  target.appendChild(content);
  document.body.appendChild(target);
  rs.useFakeTimers();
});

afterEach(() => {
  cleanup();
  target.remove();
  rs.useRealTimers();
  appearance.value = {
    preferences: { treatment: "retro", motion: true, logo: null, label: "" },
    motionOn: true,
  };
});

describe("RetroResolve", () => {
  it("steps the pixelation filter down on the persistent target and removes it entirely when done, without ever restructuring its children", () => {
    render(<RetroResolve />);

    // Applied immediately at mount, at the coarsest step, directly on the
    // persistent target — no wrapper is created, and the marker child never
    // moves.
    expect(document.querySelector(WRAPPER_SELECTOR)).toBeNull();
    expect(target.style.filter).toMatch(/^url\(#/);
    expect(content.parentElement).toBe(target);

    act(() => {
      rs.advanceTimersByTime(300);
    });
    // Still mid-resolve: the filter is still applied.
    expect(target.style.filter).toMatch(/^url\(#/);
    expect(content.parentElement).toBe(target);

    act(() => {
      rs.advanceTimersByTime(400);
    });
    // Fully resolved: filter removed entirely, not just set to none; content
    // was never touched.
    expect(target.style.filter).toBe("");
    expect(content.parentElement).toBe(target);
    expect(document.querySelector(WRAPPER_SELECTOR)).toBeNull();
  });

  it("skips the resolve entirely under reduced motion / brand motion off", () => {
    appearance.value = {
      preferences: { treatment: "retro", motion: true, logo: null, label: "" },
      motionOn: false,
    };
    render(<RetroResolve />);
    expect(target.style.filter).toBe("");

    act(() => {
      rs.advanceTimersByTime(1000);
    });
    expect(target.style.filter).toBe("");
  });

  it("does nothing outside the retro treatment", () => {
    appearance.value = {
      preferences: { treatment: "paper", motion: true, logo: null, label: "" },
      motionOn: true,
    };
    const { container } = render(<RetroResolve />);
    expect(container.firstChild).toBeNull();
    expect(target.style.filter).toBe("");
  });

  it("does nothing when the persistent target is not in the DOM yet", () => {
    target.remove();
    expect(() => render(<RetroResolve />)).not.toThrow();
  });

  it("clears the filter on cleanup even mid-resolve (route change away from retro)", () => {
    const { unmount } = render(<RetroResolve />);
    expect(target.style.filter).toMatch(/^url\(#/);

    act(() => {
      rs.advanceTimersByTime(150);
    });
    expect(target.style.filter).toMatch(/^url\(#/);

    unmount();
    expect(target.style.filter).toBe("");
    expect(content.parentElement).toBe(target);
  });

  it("never throws when the target's real content is swapped out from under it mid-resolve (regression: /workspace/agents replacing its loading state for the real page or an error the instant /api/features answers used to crash with 'Failed to execute removeChild on Node: the node to be removed is not a child of this node', because an earlier version moved #workspace-main's children into an effect-created wrapper React didn't know about)", () => {
    // A stand-in for AgentsLayout: its whole top-level rendered node changes
    // shape (a div while loading, a different element type once settled),
    // as a direct child of the same persistent target RetroResolve filters.
    function AgentsLikeContent() {
      const [loading, setLoading] = useState(true);
      return (
        <>
          {loading ? (
            <div className="flex size-full items-center justify-center">
              <div data-testid="loading">Loading agents…</div>
            </div>
          ) : (
            <>
              <div data-testid="loaded">Agents loaded</div>
            </>
          )}
          <button
            type="button"
            data-testid="settle"
            onClick={() => setLoading(false)}
          >
            settle
          </button>
        </>
      );
    }

    // This test supplies its own content; drop the shared marker child so
    // AgentsLikeContent is the only thing React manages inside target.
    content.remove();

    // Render AgentsLikeContent directly into the same persistent target
    // RetroResolve targets, exactly like WorkspaceContent nests {children}
    // inside #workspace-main-content.
    const { getByTestId } = render(<AgentsLikeContent />, {
      container: target,
    });
    render(<RetroResolve />);
    expect(target.style.filter).toMatch(/^url\(#/);
    expect(getByTestId("loading")).toBeTruthy();

    act(() => {
      rs.advanceTimersByTime(100);
    });

    // The route settles (successfully or not) well inside the ~600ms
    // resolve window, swapping the target's entire top-level child. This
    // must not throw, and the resolve must keep running normally on the
    // untouched target afterward.
    expect(() => {
      act(() => {
        getByTestId("settle").click();
      });
    }).not.toThrow();

    expect(getByTestId("loaded")).toBeTruthy();
    expect(target.style.filter).toMatch(/^url\(#/);

    act(() => {
      rs.advanceTimersByTime(500);
    });
    expect(target.style.filter).toBe("");
  });
});
