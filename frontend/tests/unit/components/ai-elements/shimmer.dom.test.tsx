import { describe, expect, it, rs } from "@rstest/core";
import { render, screen } from "@testing-library/react";

rs.mock("motion/react", () => ({
  motion: {
    // Marker proves the infinite JS animation path rendered.
    create: () => (props: Record<string, unknown>) => (
      <div data-testid="motion-shimmer" {...props} />
    ),
  },
}));

function mockReducedMotion(matches: boolean) {
  window.matchMedia = ((query: string) =>
    ({
      matches: matches && query.includes("prefers-reduced-motion"),
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }) as unknown) as typeof window.matchMedia;
}

describe("Shimmer", () => {
  it("renders plain same text with no Motion component when reduced motion is preferred", async () => {
    mockReducedMotion(true);
    const { Shimmer } = await import("@/components/ai-elements/shimmer");

    render(<Shimmer>Thinking...</Shimmer>);

    expect(screen.getByText("Thinking...")).toBeTruthy();
    expect(screen.queryByTestId("motion-shimmer")).toBeNull();
  });
});
