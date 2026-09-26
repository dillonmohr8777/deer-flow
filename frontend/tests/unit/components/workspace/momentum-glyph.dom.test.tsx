import { afterEach, describe, expect, it } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { MomentumGlyph } from "@/components/workspace/command-center/momentum-glyph";

afterEach(cleanup);

describe("MomentumGlyph", () => {
  it("keeps a seed stable while giving different identities distinct vectors", () => {
    render(
      <>
        <MomentumGlyph seed="agent:reviewer" label="Reviewer one" />
        <MomentumGlyph seed="agent:reviewer" label="Reviewer two" />
        <MomentumGlyph seed="agent:writer" label="Writer" />
      </>,
    );

    const reviewerOne = screen.getByRole("img", { name: "Reviewer one" });
    const reviewerTwo = screen.getByRole("img", { name: "Reviewer two" });
    const writer = screen.getByRole("img", { name: "Writer" });

    expect(reviewerOne.getAttribute("data-momentum-glyph")).toBe(
      reviewerTwo.getAttribute("data-momentum-glyph"),
    );
    expect(reviewerOne.getAttribute("data-momentum-glyph")).not.toBe(
      writer.getAttribute("data-momentum-glyph"),
    );
  });

  it("keeps decorative glyphs silent and draws no gradients", () => {
    const { container } = render(
      <>
        <MomentumGlyph seed="thread:alpha" size={24} />
        <MomentumGlyph seed="thread:alpha" label="Alpha conversation" />
      </>,
    );

    const glyphs = container.querySelectorAll("svg[data-momentum-glyph]");
    expect(glyphs[0]?.getAttribute("aria-hidden")).toBe("true");
    expect(glyphs[0]?.getAttribute("role")).toBeNull();
    expect(glyphs[0]?.getAttribute("width")).toBe("24");
    expect(glyphs[0]?.getAttribute("height")).toBe("24");
    expect(
      screen.getByRole("img", { name: "Alpha conversation" }),
    ).toBeDefined();

    // 6faebd2b replaced gradient strokes with flat ink and cream; no gradient
    // ids exist to collide, and none should come back.
    expect(container.querySelectorAll("linearGradient")).toHaveLength(0);
  });

  it("draws no brass at any size: a resting identity carries no pin", () => {
    const { container } = render(
      <>
        <MomentumGlyph seed="agent:omega-reporting" size={24} />
        <MomentumGlyph seed="agent:omega-reporting" size={56} initial="Omega" />
        <MomentumGlyph seed="agent:omega-reporting" size={96} />
      </>,
    );
    expect(container.innerHTML.toLowerCase()).not.toContain("#c8a04a");
  });
});
