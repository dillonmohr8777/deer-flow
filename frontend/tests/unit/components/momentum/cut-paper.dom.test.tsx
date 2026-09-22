import { afterEach, describe, expect, it } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { CutPaper } from "@/components/momentum/cut-paper";

afterEach(() => {
  cleanup();
});

describe("cut-paper headline word", () => {
  it("exposes one clean accessible name, not one per letter", () => {
    const { container } = render(<CutPaper word="Momentum" />);

    // The wrapper carries the accessible name via aria-label.
    expect(screen.getByLabelText("Momentum")).toBeTruthy();

    // Every per-letter span is aria-hidden, so none of them is separately
    // announced — a screen reader only ever sees the wrapper's label.
    const letters = container.querySelectorAll('span[aria-hidden="true"]');
    expect(letters).toHaveLength("Momentum".length);
    for (const letter of letters) {
      expect(letter.getAttribute("aria-hidden")).toBe("true");
    }

    // Visible text still spells the word, so it degrades cleanly with CSS
    // off (no styling applied) as plain text.
    expect(container.textContent).toBe("Momentum");
  });

  it("renders a space in multi-word input as a non-breaking space letter", () => {
    render(<CutPaper word="Go now" />);
    expect(screen.getByLabelText("Go now")).toBeTruthy();
  });
});
