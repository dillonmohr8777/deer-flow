import { afterEach, describe, expect, it } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import {
  SkipToContent,
  WORKSPACE_MAIN_ID,
} from "@/components/workspace/skip-to-content";

afterEach(cleanup);

describe("SkipToContent", () => {
  it("is the first tab stop and targets the workspace main region", () => {
    render(
      <>
        <SkipToContent />
        <nav>
          <button type="button">Sidebar control</button>
        </nav>
        <main id={WORKSPACE_MAIN_ID} tabIndex={-1} />
      </>,
    );
    const link = screen.getByRole("link", { name: "Skip to content" });
    expect(link.getAttribute("href")).toBe(`#${WORKSPACE_MAIN_ID}`);
    expect(document.querySelector("a")).toBe(link);
    expect(document.getElementById(WORKSPACE_MAIN_ID)?.tabIndex).toBe(-1);
  });
});
