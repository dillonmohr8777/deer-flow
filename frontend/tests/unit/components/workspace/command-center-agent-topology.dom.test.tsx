import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { AgentTopology } from "@/components/workspace/command-center/agent-topology";

afterEach(cleanup);

describe("AgentTopology", () => {
  it("renders the lead, specialist states, and selection semantics", () => {
    const onSelect = rs.fn();
    render(
      <AgentTopology
        leadLabel="Dillon Brain"
        leadHref="/workspace/chats/new"
        selectedName="dillon-reviewer"
        onSelect={onSelect}
        roster={[
          { name: "dillon-reviewer", display_name: "Reviewer", enabled: true },
          { name: "dillon-writer", display_name: "Writer", enabled: false },
        ]}
      />,
    );

    expect(screen.getByText("Dillon Brain")).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Open lead agent conversation" })
        .getAttribute("href"),
    ).toBe("/workspace/chats/new");
    expect(screen.getByText("Enabled")).toBeTruthy();
    expect(screen.getByText("Disabled")).toBeTruthy();
    expect(screen.getAllByText("Live state unknown")).toHaveLength(2);
    expect(
      screen
        .getByRole("button", { name: /Reviewer/ })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: /Writer/ }));
    expect(onSelect).toHaveBeenCalledWith("dillon-writer");
  });

  it("keeps definition state separate from recorded runtime state", () => {
    render(
      <AgentTopology
        leadLabel="Dillon Brain"
        leadHref="/workspace/chats/new"
        selectedName={null}
        runtimeKnown
        activeAgentNames={["dillon-reviewer"]}
        onSelect={rs.fn()}
        roster={[
          { name: "dillon-reviewer", display_name: "Reviewer", enabled: true },
          { name: "dillon-writer", display_name: "Writer", enabled: false },
        ]}
      />,
    );

    expect(screen.getByText("Active run recorded")).toBeTruthy();
    expect(screen.getByText("Idle")).toBeTruthy();
    expect(screen.getByText("Disabled")).toBeTruthy();
  });

  it("renders the lead and every specialist through MomoAvatar's procedural glyph fallback, with no <img> and no empty box (momos/ ships empty)", () => {
    const { container } = render(
      <AgentTopology
        leadLabel="Dillon Brain"
        leadHref="/workspace/chats/new"
        selectedName={null}
        onSelect={rs.fn()}
        roster={[
          { name: "dillon-reviewer", display_name: "Reviewer", enabled: true },
          { name: "dillon-writer", display_name: "Writer", enabled: false },
        ]}
      />,
    );

    // No <img> anywhere: AVAILABLE_MOMO_SLUGS is empty, so both the lead
    // and every specialist call site must fall through to the procedural
    // MomentumGlyph fallback inside MomoAvatar - no 404 request, no flash.
    expect(container.querySelectorAll("img")).toHaveLength(0);
    // Lead + 2 specialists = 3 rendered glyphs, none of them an empty box.
    expect(container.querySelectorAll("svg[data-momentum-glyph]")).toHaveLength(3);
  });
});
