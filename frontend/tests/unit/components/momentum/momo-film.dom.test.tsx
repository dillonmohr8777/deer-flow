import { describe, expect, it, rs } from "@rstest/core";
import { render } from "@testing-library/react";

import { MomoFilm } from "@/components/momentum/momo-film";

describe("MomoFilm", () => {
  it("shows the poster and plays only while live", () => {
    const play = rs
      .spyOn(HTMLMediaElement.prototype, "play")
      .mockResolvedValue(undefined);
    const pause = rs
      .spyOn(HTMLMediaElement.prototype, "pause")
      .mockImplementation(() => undefined);

    const { container, rerender } = render(
      <MomoFilm name="momo-hello" live={false} />,
    );
    const video = container.querySelector("video")!;
    expect(video.getAttribute("poster")).toBe(
      "/momentum/films/momo-hello.webp",
    );
    expect(video.getAttribute("preload")).toBe("none");
    expect(video.muted).toBe(true);
    expect(play).not.toHaveBeenCalled();

    rerender(<MomoFilm name="momo-hello" live />);
    expect(play).toHaveBeenCalledTimes(1);

    rerender(<MomoFilm name="momo-hello" live={false} />);
    expect(pause).toHaveBeenCalled();
  });
});
