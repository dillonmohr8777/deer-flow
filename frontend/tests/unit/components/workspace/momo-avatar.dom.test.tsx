import { afterEach, describe, expect, it } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { MomentumGlyph } from "@/components/workspace/command-center/momentum-glyph";
import { MomoAvatar } from "@/components/workspace/command-center/momo-avatar";

afterEach(cleanup);

// Same live roster this repo actually has (fleet/agents/*/config.yaml).
const KNOWN_AGENT = {
  name: "analytics-engineer",
  display_name: "Analytics Engineer",
  description: "Builds independently reconciled metrics and client-ready analytics specifications.",
};
const UNKNOWN_AGENT = { name: "some-future-specialist", display_name: "Future Specialist" };

describe("MomoAvatar", () => {
  it("renders an <img> at the expected slug path for a known agent name", () => {
    render(<MomoAvatar agent={KNOWN_AGENT} size={40} />);
    const el = screen.getByRole("img", {
      name: /Analytics Engineer/,
    });
    const img = el.querySelector("img");
    expect(img).toBeTruthy();
    expect(img?.getAttribute("src")).toBe("/momentum/momos/analytics.svg");
    // The decorative <img> must not double-announce: the wrapper owns the name.
    expect(img?.getAttribute("alt")).toBe("");
    expect(img?.getAttribute("aria-hidden")).toBe("true");
    expect(el.querySelector("svg[data-momentum-glyph]")).toBeNull();
  });

  it("renders MomentumGlyph with the same seed an unknown agent would have had without MomoAvatar", () => {
    const { container: withAvatar } = render(
      <MomoAvatar agent={UNKNOWN_AGENT} size={40} />,
    );
    // MomoAvatar passes the display name through so an unmapped agent gets a
    // monogram rather than an abstract mark, so the direct comparison has to
    // hand the glyph the same name.
    const { container: direct } = render(
      <MomentumGlyph
        seed={`agent:${UNKNOWN_AGENT.name}`}
        initial={UNKNOWN_AGENT.display_name}
        size={40}
      />,
    );

    const avatarGlyph = withAvatar.querySelector("svg[data-momentum-glyph]");
    const directGlyph = direct.querySelector("svg[data-momentum-glyph]");
    expect(avatarGlyph?.getAttribute("data-momentum-glyph")).toBe(
      directGlyph?.getAttribute("data-momentum-glyph"),
    );
  });

  it("gives every agent on the current roster its own shipped Momo, no glyph fallback", () => {
    // The roster is fleet/agents/*/config.yaml. Every one of them now has
    // artwork, so a glyph appearing here means a slug lost its mapping or its
    // file.
    const roster = [
      [KNOWN_AGENT, "analytics"],
      [{ name: "data-migration-engineer", display_name: "Data Migration Engineer" }, "migration"],
      [{ name: "independent-verifier", display_name: "Independent Verifier" }, "verifier"],
      [{ name: "fleet-scout", display_name: "Fleet Scout" }, "research"],
      [{ name: "fleet-builder", display_name: "Fleet Builder" }, "builder"],
      [{ name: "fleet-qa", display_name: "Fleet QA" }, "qa"],
      [{ name: "fleet-reliability", display_name: "Fleet Reliability" }, "reliability"],
      [{ name: "senior-software-engineer", display_name: "Senior Software Engineer" }, "engineer"],
    ] as const;

    const { container } = render(
      <>
        {roster.map(([agent]) => (
          <MomoAvatar key={agent.name} agent={agent} size={40} />
        ))}
      </>,
    );

    expect(container.querySelectorAll("svg[data-momentum-glyph]")).toHaveLength(0);
    const sources = [...container.querySelectorAll("img")].map((img) =>
      img.getAttribute("src"),
    );
    expect(sources).toEqual(
      roster.map(([, slug]) => `/momentum/momos/${slug}.svg`),
    );
  });

  it("falls back to the glyph for an agent with no shipped Momo", () => {
    const { container } = render(<MomoAvatar agent={UNKNOWN_AGENT} size={40} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("svg[data-momentum-glyph]")).toBeTruthy();
  });

  it("marks itself data-size=\"sm\" at 48px and below", () => {
    const { container } = render(<MomoAvatar agent={KNOWN_AGENT} size={40} />);
    expect(
      container.querySelector('[role="img"]')?.getAttribute("data-size"),
    ).toBe("sm");
  });

  it("marks decoration aria-hidden while the wrapper alone carries the accessible name", () => {
    // Holds for both renderings: shipped artwork (<img>) and the glyph
    // fallback (inline <svg>). Whichever one is inside, it must not be
    // announced separately from the wrapper.
    for (const agent of [KNOWN_AGENT, UNKNOWN_AGENT]) {
      const { container, unmount } = render(<MomoAvatar agent={agent} size={40} />);
      const decoration = container.querySelector("img, svg");
      expect(decoration).toBeTruthy();
      expect(decoration?.getAttribute("aria-hidden")).toBe("true");
      unmount();
    }
  });
});
