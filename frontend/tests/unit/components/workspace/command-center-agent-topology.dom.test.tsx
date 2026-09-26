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

  it("says how many specialists the lead delegates to, only once they load", () => {
    const props = {
      leadLabel: "Dillon Brain",
      leadHref: "/workspace/chats/new",
      selectedName: null,
      onSelect: rs.fn(),
      roster: [
        { name: "dillon-reviewer", display_name: "Reviewer", enabled: true },
        { name: "dillon-writer", display_name: "Writer", enabled: false },
      ],
    };
    render(<AgentTopology {...props} />);
    expect(screen.getByText("Delegates to 2 specialists")).toBeTruthy();
    cleanup();
    render(<AgentTopology {...props} loading />);
    expect(screen.queryByText(/Delegates to/)).toBeNull();
    cleanup();
    render(<AgentTopology {...props} error />);
    expect(screen.queryByText(/Delegates to/)).toBeNull();
    cleanup();
    render(<AgentTopology {...props} roster={props.roster.slice(0, 1)} />);
    expect(screen.getByText("Delegates to 1 specialist")).toBeTruthy();
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

  it("pins only a specialist with an active run, with the working squares", () => {
    const roster = [
      { name: "dillon-reviewer", display_name: "Reviewer", enabled: true },
      { name: "dillon-writer", display_name: "Writer", enabled: true },
    ];
    const { rerender } = render(
      <AgentTopology
        leadLabel="Dillon Brain"
        leadHref="/workspace/chats/new"
        selectedName={null}
        runtimeKnown
        activeAgentNames={["dillon-reviewer"]}
        onSelect={rs.fn()}
        roster={roster}
      />,
    );

    const working = screen.getByRole("button", { name: /Reviewer/ });
    const idle = screen.getByRole("button", { name: /Writer/ });
    expect(working.classList.contains("pinned")).toBe(true);
    const squares = working.querySelector(".paper-pixels");
    expect(squares?.getAttribute("data-active")).toBe("true");
    expect(squares?.getAttribute("aria-hidden")).toBe("true");
    // An idle card is not pinned: a pin says something is happening.
    expect(idle.classList.contains("pinned")).toBe(false);
    expect(idle.querySelector(".paper-pixels")).toBeNull();

    // Nobody is working: no pins anywhere, however many specialists exist.
    rerender(
      <AgentTopology
        leadLabel="Dillon Brain"
        leadHref="/workspace/chats/new"
        selectedName={null}
        runtimeKnown
        activeAgentNames={[]}
        onSelect={rs.fn()}
        roster={roster}
      />,
    );
    expect(document.querySelectorAll(".pinned, .paper-pixels")).toHaveLength(0);

    // Unknown live state is not activity either, even for a listed name.
    rerender(
      <AgentTopology
        leadLabel="Dillon Brain"
        leadHref="/workspace/chats/new"
        selectedName={null}
        runtimeKnown={false}
        activeAgentNames={["dillon-reviewer"]}
        onSelect={rs.fn()}
        roster={roster}
      />,
    );
    expect(document.querySelectorAll(".pinned, .paper-pixels")).toHaveLength(0);
  });

  it("draws the lead as Dillon Brain's PaperLayers art at 160 and specialists at 56, not a lettered monogram", () => {
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

    // No appearance mock here: the context default (motion off) holds
    // PaperLayers to its flattened fallback, decorative beside the name.
    const lead = container.querySelector(
      'img[src="/momentum/brain/flat.webp"]',
    );
    expect(lead?.getAttribute("width")).toBe("160");
    expect(lead?.getAttribute("alt")).toBe("");
    // Specialists without a mapped Momo fall back to MomoAvatar's glyph, at
    // the 56px specialist size (CSS draws it at 40 on phones); the lead no
    // longer renders a glyph at all.
    const glyphs = container.querySelectorAll("svg[data-momentum-glyph]");
    expect(glyphs).toHaveLength(2);
    for (const glyph of glyphs) expect(glyph.getAttribute("width")).toBe("56");
    // The avatar is hidden from assistive tech: the card's name says it once.
    expect(
      screen.getByRole("button", { name: /Reviewer/ }).textContent,
    ).toContain("Reviewer");
    expect(screen.queryAllByRole("img")).toHaveLength(0);
  });
});
