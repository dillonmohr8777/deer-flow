import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";

import { MomentumLanding } from "@/components/momentum/landing/momentum-landing";
import {
  COMIC_ATTR,
  COMIC_SESSION_KEY,
  STORM,
} from "@/components/momentum/momobot/comic-data";

function mockMedia({ reduce }: { reduce: boolean }) {
  window.matchMedia = ((query: string) => ({
    matches: query.includes("reduced-motion") ? reduce : false,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  })) as unknown as typeof window.matchMedia;
}

/** A controllable stand-in for Web Animations: finish() settles `finished`. */
function mockAnimate() {
  const made: Array<{ finish: () => void }> = [];
  const animate = rs.fn(() => {
    let done!: () => void;
    const finished = new Promise<void>((res) => (done = res));
    const a = {
      finished,
      ready: Promise.resolve(),
      playState: "running",
      currentTime: 0,
      finish: () => done(),
      cancel: () => undefined,
      pause: () => undefined,
      play: () => undefined,
    };
    made.push(a);
    return a;
  });
  Object.defineProperty(Element.prototype, "animate", {
    configurable: true,
    value: animate,
  });
  return { animate, made };
}

const overlayPages = () =>
  document.querySelectorAll("[data-comic-stack] > div");
const html = () => document.documentElement;

beforeEach(() => {
  html().removeAttribute(COMIC_ATTR);
  sessionStorage.clear();
  Object.defineProperty(HTMLImageElement.prototype, "decode", {
    configurable: true,
    value: () => Promise.resolve(),
  });
});

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
  // happy-dom has no Web Animations; drop the stub between tests.
  delete (Element.prototype as { animate?: unknown }).animate;
});

describe("front door comic intro", () => {
  it("never plays under reduced motion: the settled hero is there at once", () => {
    mockMedia({ reduce: true });
    render(<MomentumLanding />);
    expect(html().getAttribute(COMIC_ATTR)).toBe("done");
    expect(overlayPages()).toHaveLength(0);
    expect(
      screen.getByRole("heading", { level: 1, name: "Say hello to MomoBot" }),
    ).toBeDefined();
    expect(screen.queryByRole("button", { name: /motion/ })).toBeNull();
  });

  it("plays once per session", () => {
    mockMedia({ reduce: false });
    sessionStorage.setItem(COMIC_SESSION_KEY, "1");
    render(<MomentumLanding />);
    expect(html().getAttribute(COMIC_ATTR)).toBe("done");
    expect(overlayPages()).toHaveLength(0);
    // The wall is up, with its Pause motion control.
    expect(screen.getByRole("button", { name: "Pause motion" })).toBeDefined();
  });

  it("plays on a first visit, and any key skips to the settled page", async () => {
    mockMedia({ reduce: false });
    const { made } = mockAnimate();
    render(<MomentumLanding />);
    expect(html().getAttribute(COMIC_ATTR)).toBe("play");
    expect(sessionStorage.getItem(COMIC_SESSION_KEY)).toBe("1");
    expect(overlayPages()).toHaveLength(1 + STORM.length + 3);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0)); // first beat: cold-open art and the display face
    });
    expect(made.length).toBeGreaterThan(100); // the timeline is running
    await act(async () => {
      fireEvent.keyDown(window, { key: " " });
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(html().getAttribute(COMIC_ATTR)).toBe("done");
    expect(overlayPages()).toHaveLength(0);
    expect(
      screen.getByRole("heading", { level: 1, name: "Say hello to MomoBot" }),
    ).toBeDefined();
  });

  it("goes straight to the settled page without Web Animations", async () => {
    mockMedia({ reduce: false });
    render(<MomentumLanding />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(html().getAttribute(COMIC_ATTR)).toBe("done");
    expect(overlayPages()).toHaveLength(0);
  });
});
