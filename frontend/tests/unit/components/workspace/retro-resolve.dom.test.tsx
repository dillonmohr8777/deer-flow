import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { act, cleanup, render } from "@testing-library/react";

import { type BrandTreatment } from "@/components/workspace/command-center/appearance-preferences";
import { RetroResolve } from "@/components/workspace/command-center/retro-resolve";
import { WORKSPACE_MAIN_ID } from "@/components/workspace/skip-to-content";

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

let main: HTMLElement;
let content: HTMLElement;

beforeEach(() => {
  main = document.createElement("main");
  main.id = WORKSPACE_MAIN_ID;
  // A marker child so wrapping/unwrapping is observable, not just the
  // filter value — the resolve must never lose or duplicate real content.
  content = document.createElement("h1");
  content.textContent = "Mission Control";
  main.appendChild(content);
  document.body.appendChild(main);
  rs.useFakeTimers();
});

afterEach(() => {
  cleanup();
  main.remove();
  rs.useRealTimers();
  appearance.value = {
    preferences: { treatment: "retro", motion: true, logo: null, label: "" },
    motionOn: true,
  };
});

describe("RetroResolve", () => {
  it("wraps main's content, steps the pixelation filter down, and unwraps with the filter removed entirely when done", () => {
    render(<RetroResolve />);

    // Applied immediately at mount, at the coarsest step, on a wrapper
    // around the existing content — not on #workspace-main itself.
    let wrapper = main.querySelector<HTMLElement>(WRAPPER_SELECTOR);
    expect(wrapper).not.toBeNull();
    expect(wrapper!.style.filter).toMatch(/^url\(#/);
    expect(wrapper!.contains(content)).toBe(true);
    expect(main.style.filter).toBe("");

    act(() => {
      rs.advanceTimersByTime(300);
    });
    // Still mid-resolve: the wrapper (and its filter) is still there.
    wrapper = main.querySelector<HTMLElement>(WRAPPER_SELECTOR);
    expect(wrapper).not.toBeNull();
    expect(wrapper!.style.filter).toMatch(/^url\(#/);

    act(() => {
      rs.advanceTimersByTime(400);
    });
    // Fully resolved: unwrapped — no wrapper left, content is back as a
    // direct child of main, filter removed entirely, not just set to none.
    expect(main.querySelector(WRAPPER_SELECTOR)).toBeNull();
    expect(content.parentElement).toBe(main);
    expect(content.style.filter).toBe("");
  });

  it("skips the resolve entirely under reduced motion / brand motion off", () => {
    appearance.value = {
      preferences: { treatment: "retro", motion: true, logo: null, label: "" },
      motionOn: false,
    };
    render(<RetroResolve />);
    expect(main.querySelector(WRAPPER_SELECTOR)).toBeNull();
    expect(content.parentElement).toBe(main);

    act(() => {
      rs.advanceTimersByTime(1000);
    });
    expect(main.querySelector(WRAPPER_SELECTOR)).toBeNull();
    expect(content.parentElement).toBe(main);
  });

  it("does nothing outside the retro treatment", () => {
    appearance.value = {
      preferences: { treatment: "paper", motion: true, logo: null, label: "" },
      motionOn: true,
    };
    const { container } = render(<RetroResolve />);
    expect(container.firstChild).toBeNull();
    expect(main.querySelector(WRAPPER_SELECTOR)).toBeNull();
  });

  it("unwraps on cleanup even mid-resolve (route change away from retro)", () => {
    const { unmount } = render(<RetroResolve />);
    expect(main.querySelector(WRAPPER_SELECTOR)).not.toBeNull();

    act(() => {
      rs.advanceTimersByTime(150);
    });
    expect(main.querySelector(WRAPPER_SELECTOR)).not.toBeNull();

    unmount();
    expect(main.querySelector(WRAPPER_SELECTOR)).toBeNull();
    expect(content.parentElement).toBe(main);
  });
});
