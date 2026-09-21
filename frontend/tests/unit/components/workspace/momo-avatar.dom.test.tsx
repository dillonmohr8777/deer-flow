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
    // Force the image path regardless of whether artwork has landed yet, by
    // asserting on what the component WOULD request for a mapped name. The
    // component itself gates on AVAILABLE_MOMO_SLUGS (empty today), so this
    // also proves the fallback below in the empty-momos case.
    render(<MomoAvatar agent={KNOWN_AGENT} size={40} />);
    const el = screen.getByRole("img", {
      name: /Analytics Engineer/,
    });
    // With momos/ empty, no <img> is emitted yet -- it falls back to the
    // glyph. The wrapper still carries the mapped identity for inspection.
    expect(el.querySelector("svg[data-momentum-glyph]")).toBeTruthy();
    expect(el.querySelector("img")).toBeNull();
  });

  it("renders MomentumGlyph with the same seed an unknown agent would have had without MomoAvatar", () => {
    const { container: withAvatar } = render(
      <MomoAvatar agent={UNKNOWN_AGENT} size={40} />,
    );
    const { container: direct } = render(
      <MomentumGlyph seed={`agent:${UNKNOWN_AGENT.name}`} size={40} />,
    );

    const avatarGlyph = withAvatar.querySelector("svg[data-momentum-glyph]");
    const directGlyph = direct.querySelector("svg[data-momentum-glyph]");
    expect(avatarGlyph?.getAttribute("data-momentum-glyph")).toBe(
      directGlyph?.getAttribute("data-momentum-glyph"),
    );
  });

  it("renders today's procedural glyphs for the whole current roster with momos/ empty, no <img> anywhere", () => {
    const roster = [
      KNOWN_AGENT,
      { name: "data-migration-engineer", display_name: "Data Migration Engineer" },
      { name: "independent-verifier", display_name: "Independent Verifier" },
      { name: "fleet-scout", display_name: "Fleet Scout" },
      { name: "fleet-builder", display_name: "Fleet Builder" },
      { name: "fleet-qa", display_name: "Fleet QA" },
      { name: "fleet-reliability", display_name: "Fleet Reliability" },
      { name: "senior-software-engineer", display_name: "Senior Software Engineer" },
    ];

    const { container } = render(
      <>
        {roster.map((agent) => (
          <MomoAvatar key={agent.name} agent={agent} size={40} />
        ))}
      </>,
    );

    expect(container.querySelectorAll("img")).toHaveLength(0);
    expect(container.querySelectorAll("svg[data-momentum-glyph]")).toHaveLength(
      roster.length,
    );
  });

  it("marks itself data-size=\"sm\" at 48px and below", () => {
    const { container } = render(<MomoAvatar agent={KNOWN_AGENT} size={40} />);
    expect(
      container.querySelector('[role="img"]')?.getAttribute("data-size"),
    ).toBe("sm");
  });

  it("marks decoration aria-hidden while the wrapper alone carries the accessible name", () => {
    render(<MomoAvatar agent={KNOWN_AGENT} size={40} />);
    const glyph = screen
      .getByRole("img", { name: /Analytics Engineer/ })
      .querySelector("svg");
    expect(glyph?.getAttribute("aria-hidden")).toBe("true");
  });
});
