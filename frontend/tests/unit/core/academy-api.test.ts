import { beforeEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: rs.fn(() => "") }));

import { getAcademy } from "@/core/academy/api";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

beforeEach(() => {
  rs.mocked(fetch).mockReset();
  rs.mocked(getBackendBaseURL).mockReturnValue("");
});

describe("Academy media origin", () => {
  it.each(["", "https://gateway.example"])(
    "loads private media from the configured backend: %s",
    async (base) => {
      rs.mocked(getBackendBaseURL).mockReturnValue(base);
      const paths = {
        video_url: "/api/academy/media/00-platform-tour.mp4",
        video_poster_url: "/api/academy/media/00-platform-tour.jpg",
        video_captions_url: "/api/academy/media/00-platform-tour.vtt",
        video_transcript_url: "/api/academy/media/00-platform-tour.txt",
      };
      rs.mocked(fetch).mockResolvedValue(
        Response.json({ tracks: [{ lessons: [paths, { video_url: null }] }] }),
      );

      const academy = await getAcademy();
      expect(fetch).toHaveBeenCalledWith(`${base}/api/academy`, {
        method: "GET",
      });
      expect(academy.tracks[0]!.lessons[0]).toEqual(
        Object.fromEntries(
          Object.entries(paths).map(([key, path]) => [key, `${base}${path}`]),
        ),
      );
      expect(academy.tracks[0]!.lessons[1]!.video_url).toBeNull();
    },
  );
});
