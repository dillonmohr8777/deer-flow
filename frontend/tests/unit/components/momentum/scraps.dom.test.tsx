import { afterEach, describe, expect, it } from "@rstest/core";
import { cleanup, render } from "@testing-library/react";

import { Scraps } from "@/components/momentum/scraps";

afterEach(cleanup);

describe("Scraps", () => {
  it("renders the named pieces with their webp src", () => {
    const { container } = render(
      <Scraps names={["compass", "twine"]} live={true} />,
    );
    const imgs = container.querySelectorAll("img");
    expect(imgs).toHaveLength(2);
    expect(imgs[0]?.getAttribute("src")).toBe("/momentum/scraps/compass.webp");
    expect(imgs[1]?.getAttribute("src")).toBe("/momentum/scraps/twine.webp");
  });

  it("hides the whole cluster from the accessibility tree", () => {
    const { container } = render(<Scraps names={["compass"]} live={true} />);
    expect(container.firstElementChild?.getAttribute("aria-hidden")).toBe(
      "true",
    );
  });

  it("follows the live prop on the container", () => {
    const { container: on } = render(
      <Scraps names={["compass"]} live={true} />,
    );
    expect(on.firstElementChild?.getAttribute("data-live")).toBe("true");

    const { container: off } = render(
      <Scraps names={["compass"]} live={false} />,
    );
    expect(off.firstElementChild?.getAttribute("data-live")).toBe("false");
  });
});
