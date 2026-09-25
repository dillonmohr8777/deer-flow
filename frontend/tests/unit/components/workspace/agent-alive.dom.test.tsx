import { afterEach, describe, expect, it } from "@rstest/core";
import { cleanup, render } from "@testing-library/react";

import { AgentAlive } from "@/components/workspace/command-center/agent-alive";
import type { AgentLife } from "@/components/workspace/command-center/agent-life";

afterEach(cleanup);

const DONE: AgentLife = { state: "done", at: "2026-09-24T12:00:00Z" };

function renderAlive(life: AgentLife, motion = true) {
  const view = render(
    <AgentAlive life={life} motion={motion}>
      <img alt="" src="/momentum/momos/qa.svg" />
    </AgentAlive>,
  );
  const alive = () =>
    view.container.querySelector<HTMLElement>(".paper-alive")!;
  return { ...view, alive };
}

describe("AgentAlive", () => {
  it("idle: still, no pin, no stamp", () => {
    const { alive } = renderAlive({ state: "idle" });
    expect(alive().dataset.alive).toBe("idle");
    expect(alive().classList.contains("pinned")).toBe(false);
    expect(alive().querySelector(".paper-alive-stamp")).toBeNull();
  });

  it("thinking: tilts, but is not pinned", () => {
    const { alive } = renderAlive({ state: "thinking" });
    expect(alive().dataset.alive).toBe("thinking");
    expect(alive().classList.contains("pinned")).toBe(false);
  });

  it("running: pinned, and the only state that wears the pin", () => {
    const { alive } = renderAlive({ state: "running" });
    expect(alive().dataset.alive).toBe("running");
    expect(alive().classList.contains("pinned")).toBe(true);
  });

  it("done: a stamp dated from the run", () => {
    const { alive } = renderAlive(DONE);
    expect(alive().dataset.alive).toBe("done");
    expect(alive().querySelector(".paper-alive-stamp")?.textContent).toBe(
      "Sep 24",
    );
    expect(alive().classList.contains("pinned")).toBe(false);
  });

  it("failed: torn, never pinned or stamped", () => {
    const { alive } = renderAlive({ state: "failed", at: DONE.at });
    expect(alive().dataset.alive).toBe("failed");
    expect(alive().classList.contains("pinned")).toBe(false);
    expect(alive().querySelector(".paper-alive-stamp")).toBeNull();
  });

  it("is decoration: hidden from assistive tech", () => {
    const { alive } = renderAlive({ state: "running" });
    expect(alive().getAttribute("aria-hidden")).toBe("true");
  });

  it("reduced motion or the motion setting off renders every state static", () => {
    for (const life of [
      { state: "idle" },
      { state: "thinking" },
      { state: "running" },
      DONE,
      { state: "failed" },
    ] satisfies AgentLife[]) {
      const { alive, unmount } = renderAlive(life, false);
      // paper.css animates only [data-live="true"]; without it the state
      // shows as its still frame (tilted, pinned, stamped or torn).
      expect(alive().dataset.live).toBeUndefined();
      expect(alive().dataset.alive).toBe(life.state);
      unmount();
    }
    const { alive } = renderAlive({ state: "running" }, true);
    expect(alive().dataset.live).toBe("true");
  });

  it("lands the stamp only when this view saw the run finish", () => {
    // Loading a page with a finished run is not a state change: no landing.
    const first = renderAlive(DONE);
    expect(first.alive().dataset.stamp).toBeUndefined();
    first.unmount();

    const { alive, rerender } = renderAlive({ state: "running" });
    rerender(
      <AgentAlive life={DONE} motion>
        <img alt="" src="/momentum/momos/qa.svg" />
      </AgentAlive>,
    );
    expect(alive().dataset.stamp).toBe("fresh");

    // A later failure clears it; nothing lands on idle -> done either.
    rerender(
      <AgentAlive life={{ state: "idle" }} motion>
        <img alt="" src="/momentum/momos/qa.svg" />
      </AgentAlive>,
    );
    rerender(
      <AgentAlive life={DONE} motion>
        <img alt="" src="/momentum/momos/qa.svg" />
      </AgentAlive>,
    );
    expect(alive().dataset.stamp).toBeUndefined();
  });
});
