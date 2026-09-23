import { afterEach, describe, expect, it } from "@rstest/core";
import { act, cleanup, render, screen } from "@testing-library/react";

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

  it("contributes the word to its heading's accessible name", () => {
    render(
      <h1>
        <span>The future needs</span> <CutPaper word="Momentum" />
      </h1>,
    );
    expect(
      screen.getByRole("heading", { name: "The future needs Momentum" }),
    ).toBeTruthy();
  });

  it("renders a space in multi-word input as a non-breaking space letter", () => {
    render(<CutPaper word="Go now" />);
    expect(screen.getByLabelText("Go now")).toBeTruthy();
  });

  it("still reveals the word when the tab was hidden at load", async () => {
    // Regression: the reveal used to be gated on brandMotionAllowed, which
    // requires visible === true. A tab that was backgrounded when the page
    // loaded therefore never settled, and because the observer disconnected on
    // that first intersection nothing ever retried — the headline stayed at
    // opacity 0 forever, even after the tab was focused.
    const observers: Array<(entries: unknown[]) => void> = [];
    const originalObserver = window.IntersectionObserver;
    const originalVisibility = Object.getOwnPropertyDescriptor(
      Document.prototype,
      "visibilityState",
    );

    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "hidden",
    });
    // @ts-expect-error -- minimal stand-in for the observer under test
    window.IntersectionObserver = class {
      constructor(callback: (entries: unknown[]) => void) {
        observers.push(callback);
      }
      observe() {
        /* driven manually via observers[] */
      }
      disconnect() {
        /* nothing to release */
      }
    };

    try {
      const { container } = render(<CutPaper word="Momentum" />);
      act(() => {
        observers.forEach((fire) => fire([{ isIntersecting: true }]));
      });

      const letters = container.querySelectorAll<HTMLElement>(
        'span[aria-hidden="true"]',
      );
      expect(letters.length).toBe("Momentum".length);
      for (const letter of letters) {
        expect(letter.style.opacity).toBe("1");
        // Hidden at load means place it, do not animate it.
        expect(letter.style.transition).toBe("none");
      }
    } finally {
      window.IntersectionObserver = originalObserver;
      if (originalVisibility) {
        Object.defineProperty(
          Document.prototype,
          "visibilityState",
          originalVisibility,
        );
      }
    }
  });
});
