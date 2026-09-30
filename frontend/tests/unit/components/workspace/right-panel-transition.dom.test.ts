import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";

import { waitForRightPanelTransition } from "@/components/workspace/chats/right-panel-transition";

class FakeTransition {
  transitionProperty = "flex-grow";
  playState: AnimationPlayState = "running";
  effect: { target: Element };
  finished: Promise<void>;
  private resolve!: () => void;
  private reject!: (reason: Error) => void;

  constructor(target: Element) {
    this.effect = { target };
    this.finished = new Promise((resolve, reject) => {
      this.resolve = resolve;
      this.reject = reject;
    });
  }

  finish() {
    this.playState = "finished";
    this.resolve();
  }

  cancel() {
    this.playState = "idle";
    this.reject(new Error("Transition replaced"));
  }
}

let frames: Map<number, FrameRequestCallback>;
let nextFrame: number;
let transitionDescriptor: PropertyDescriptor | undefined;

beforeEach(() => {
  frames = new Map();
  nextFrame = 0;
  rs.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
    frames.set(++nextFrame, callback);
    return nextFrame;
  });
  rs.spyOn(window, "cancelAnimationFrame").mockImplementation((id) => {
    frames.delete(id);
  });
  transitionDescriptor = Object.getOwnPropertyDescriptor(
    window,
    "CSSTransition",
  );
  Object.defineProperty(window, "CSSTransition", {
    configurable: true,
    value: FakeTransition,
  });
});

afterEach(() => {
  document.body.replaceChildren();
  rs.restoreAllMocks();
  if (transitionDescriptor) {
    Object.defineProperty(window, "CSSTransition", transitionDescriptor);
  } else {
    Reflect.deleteProperty(window, "CSSTransition");
  }
});

function frame() {
  const pending = Array.from(frames.values());
  frames.clear();
  pending.forEach((callback) => callback(0));
}

async function settlePromises() {
  // allSettled and its continuation each get a microtask turn.
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

function fixture() {
  const group = document.createElement("div");
  const main = document.createElement("div");
  const side = document.createElement("div");
  main.id = "main";
  side.id = "side";
  main.dataset.panel = "true";
  side.dataset.panel = "true";
  main.style.flexGrow = "60";
  side.style.flexGrow = "40";
  const animations = new Map<Element, unknown[]>([
    [main, []],
    [side, []],
  ]);
  for (const panel of [main, side]) {
    Object.defineProperty(panel, "getAnimations", {
      configurable: true,
      value: () => animations.get(panel) as Animation[],
    });
  }
  group.append(main, side);
  document.body.append(group);
  const onComplete = rs.fn();
  const start = () =>
    waitForRightPanelTransition(group, { main: 60, side: 40 }, onComplete);
  return { group, main, side, animations, onComplete, start };
}

describe("right-panel transition completion", () => {
  it("does not interpret an uncommitted DOM target as no-motion completion", () => {
    const { main, side, onComplete, start } = fixture();
    main.style.flexGrow = "100";
    side.style.flexGrow = "0";
    start();
    frame();
    expect(onComplete).not.toHaveBeenCalled();
    expect(frames.size).toBe(1);
    main.style.flexGrow = "60";
    side.style.flexGrow = "40";
    frame();
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("waits for both panels even when their transitions finish separately", async () => {
    const { main, side, animations, onComplete, start } = fixture();
    const mainTransition = new FakeTransition(main);
    const sideTransition = new FakeTransition(side);
    animations.set(main, [mainTransition]);
    animations.set(side, [sideTransition]);
    start();
    frame();
    mainTransition.finish();
    await settlePromises();
    frame();
    expect(onComplete).not.toHaveBeenCalled();
    sideTransition.finish();
    await settlePromises();
    frame();
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("rechecks a canceled transition and waits for its replacement", async () => {
    const { side, animations, onComplete, start } = fixture();
    const oldTransition = new FakeTransition(side);
    animations.set(side, [oldTransition]);
    start();
    frame();
    const replacement = new FakeTransition(side);
    animations.set(side, [replacement]);
    oldTransition.cancel();
    await settlePromises();
    frame();
    expect(onComplete).not.toHaveBeenCalled();
    replacement.finish();
    await settlePromises();
    frame();
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("completes no-motion only on the post-commit frame", () => {
    const { onComplete, start } = fixture();
    start();
    expect(onComplete).not.toHaveBeenCalled();
    frame();
    expect(onComplete).toHaveBeenCalledTimes(1);
    frame();
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("accepts a committed fractional layout with computed CSS serialization rounding", () => {
    const { group, main, side, onComplete } = fixture();
    const target = { main: 62.8765433, side: 37.1234567 };
    main.style.flexGrow = String(target.main);
    side.style.flexGrow = String(target.side);
    rs.spyOn(window, "getComputedStyle").mockImplementation(
      (element) =>
        ({
          flexGrow: Number((element as HTMLElement).style.flexGrow).toPrecision(
            6,
          ),
        }) as CSSStyleDeclaration,
    );
    waitForRightPanelTransition(group, target, onComplete);
    frame();
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("ignores descendant targets, other properties and non-CSS animations", () => {
    const { main, side, animations, onComplete, start } = fixture();
    const descendant = new FakeTransition(document.createElement("span"));
    const opacity = new FakeTransition(side);
    opacity.transitionProperty = "opacity";
    animations.set(main, [descendant]);
    animations.set(side, [
      opacity,
      { effect: { target: side }, transitionProperty: "flex-grow" },
    ]);
    start();
    frame();
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("invalidates pending frames and promise completions on cleanup", async () => {
    const first = fixture();
    const cleanupBeforeFrame = first.start();
    cleanupBeforeFrame();
    frame();
    expect(first.onComplete).not.toHaveBeenCalled();

    const second = fixture();
    const transition = new FakeTransition(second.side);
    second.animations.set(second.side, [transition]);
    const cleanupDuringTransition = second.start();
    frame();
    cleanupDuringTransition();
    transition.finish();
    await settlePromises();
    frame();
    expect(second.onComplete).not.toHaveBeenCalled();
    expect(frames.size).toBe(0);
  });

  it("snaps deliberately when transition introspection is unavailable", () => {
    const { main, side, onComplete, start } = fixture();
    Reflect.deleteProperty(window, "CSSTransition");
    main.style.setProperty("transition-property", "opacity", "important");
    const layoutRead = rs.spyOn(side, "getBoundingClientRect");
    start();
    expect(onComplete).not.toHaveBeenCalled();
    frame();
    expect(layoutRead).toHaveBeenCalled();
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(main.style.getPropertyValue("transition-property")).toBe("opacity");
    expect(main.style.getPropertyPriority("transition-property")).toBe(
      "important",
    );
    expect(side.style.getPropertyValue("transition-property")).toBe("");
  });

  it("cancels when the captured panel is detached", () => {
    const { side, onComplete, start } = fixture();
    start();
    side.remove();
    frame();
    expect(onComplete).not.toHaveBeenCalled();
    expect(frames.size).toBe(0);
  });
});
