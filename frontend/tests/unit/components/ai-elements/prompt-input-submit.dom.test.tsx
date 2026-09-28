import { describe, expect, it } from "@rstest/core";
import { render, screen } from "@testing-library/react";

import { PromptInputSubmit } from "@/components/ai-elements/prompt-input";

describe("PromptInputSubmit", () => {
  it("keeps the default variant's primary-contrast icon color", () => {
    render(<PromptInputSubmit />);

    const button = screen.getByRole("button", { name: "Submit" });

    expect(button.className).toContain("bg-primary");
    expect(button.className).toContain("text-primary-foreground");
    // A shared `text-foreground` class on the button would win the Tailwind
    // merge over `text-primary-foreground`, drawing the icon in the page's
    // default text color instead of a color paired with the primary fill.
    expect(button.className).not.toContain("text-foreground");
  });
});
