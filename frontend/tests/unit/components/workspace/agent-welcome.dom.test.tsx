import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { AgentWelcome } from "@/components/workspace/agent-welcome";
import type { Agent } from "@/core/agents";

rs.mock("@/components/workspace/command-center/appearance-provider", () => ({
  useWorkspaceAppearance: () => ({
    preferences: { treatment: "paper", motion: false, logo: null, label: "" },
    reducedMotion: true,
    visible: true,
  }),
}));

afterEach(cleanup);

function agent(overrides: Partial<Agent>): Agent {
  return {
    name: "omega-reporting",
    description: "Builds the Monday performance summary.",
    system_prompt: "",
    ...overrides,
  } as Agent;
}

describe("AgentWelcome", () => {
  it("draws the agent's roster Momo, not a generic robot icon", () => {
    const { container } = render(
      <AgentWelcome
        agent={agent({ name: "dillon-growth", display_name: "Growth" })}
        agentName="dillon-growth"
      />,
    );
    const art = container.querySelector("img[data-slug]");
    expect(art?.getAttribute("src")).toBe("/momentum/momos/growth.svg");
    expect(container.querySelector("svg.lucide")).toBeNull();
    expect(screen.getByText("Growth")).toBeDefined();
  });

  it("draws Dillon Brain's paper art for the lead", () => {
    const { container } = render(
      <AgentWelcome
        agent={agent({ name: "dillon-brain", display_name: "Dillon Brain" })}
        agentName="dillon-brain"
      />,
    );
    expect(container.innerHTML).toContain("/momentum/brain/");
  });

  it("keeps the same glyph while the agent is still loading", () => {
    const loading = render(
      <AgentWelcome agent={undefined} agentName="omega-reporting" />,
    );
    const pending = loading.container
      .querySelector("svg[data-momentum-glyph]")
      ?.getAttribute("data-momentum-glyph");
    loading.unmount();
    const { container } = render(
      <AgentWelcome
        agent={agent({ display_name: "Omega weekly reporting" })}
        agentName="omega-reporting"
      />,
    );
    const loaded = container
      .querySelector("svg[data-momentum-glyph]")
      ?.getAttribute("data-momentum-glyph");
    expect(pending).toBeTruthy();
    // Keyed by the agent's stable name, so the mark does not jump when the
    // agent record arrives.
    expect(loaded).toBe(pending);
    expect(container.querySelector("img[data-slug]")).toBeNull();
  });

  it("does not announce the mark twice: the name is the visible heading", () => {
    const { container } = render(
      <AgentWelcome
        agent={agent({ display_name: "Omega weekly reporting" })}
        agentName="omega-reporting"
      />,
    );
    expect(screen.queryByRole("img")).toBeNull();
    expect(
      container.querySelector('[aria-hidden="true"][data-size]'),
    ).toBeTruthy();
  });
});
