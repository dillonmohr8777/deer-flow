# Momo films

Higgsfield Seedance 2.5 (omni_reference, 720p, no audio), made 2026-09-23. The style and character reference is Dillon's own Momo clip. Each clip is trimmed and crossfade-looped locally with ffmpeg, then encoded to WebM (VP9), MP4 (H.264) and a WebP poster.

| Name          | Job                                  | Used on                                                              |
| ------------- | ------------------------------------ | -------------------------------------------------------------------- |
| momo-intro    | 1ae167cf-fa06-497f-a2ad-c9b39859c4dd | landing hero, pinned right of the copy (plays once, then momo-hello) |
| momo-hello    | 76660308-af3e-4927-98ac-15921cc87ca7 | sign in (loop)                                                       |
| momo-thinking | 72154ca3-2120-4ca0-b54d-74a8160645e5 | chat "working" row (loop)                                            |
| momo-daily    | f4079128-864e-4012-958f-1cccc3d1c22a | Momo Daily masthead and empty lead (loop)                            |
| momo-pencil   | 0e6214d7-2e5b-432f-9364-82e644a04cbf | empty chat (loop)                                                    |
| momo-crew     | 19219217-75f8-42b8-b55a-6d278573b19a | Agents page (plays once)                                             |
| momo-done     | 8fd685ce-09ed-461b-bff6-26f6b7a100ce | not placed yet                                                       |

All films render through `src/components/momentum/momo-film.tsx`. They are muted, never preloaded, and show only the poster when motion is off.

## momo-collage (background)

The collage background behind sign in and the landing hero. Codex rendered it on 2026-09-23 from eight OpenAI `gpt-image-2.5-sunburst` plates with more than a hundred cutouts:

- **Source:** `Documents/Codex/2026-09-23/we-ll-see-how-good-you/work/momo-collage/momo-collage-final.mp4`, SHA256 `8F257BD5...DEB36`.
- **Recipe:** `render_momo_collage.py` in the same folder.
- **Trim for the web:** only the collage part (0 to 7s), with a 0.6s crossfade at the seam, so the background never shows a second Momo. Encoded at 960x540 (about 2 MB) with a still poster.
- **Where it plays:** through `ScrapbookBackdrop`, only after the page settles, and never under reduced motion.
- **Flashes:** its biggest luminance jumps come about once a second, under the three-per-second limit.

## momo-comic-intro-20260925 (new background)

Thirty distinct original still plates were generated on 2026-09-25 with the
built-in image generation tool for this MomoBot intro update. They live in
`public/momentum/intro-comic/plates/plate-01.webp` through `plate-30.webp`.
The sequence follows the paper city through maps, research, production and
delivery; it uses the established cream, ink, royal blue and restrained brass
palette. No Marvel characters, logos or borrowed superhero artwork appear.

`frontend/scripts/render-momo-comic-intro.py` applies a small camera push and
0.2-second dissolves between plates, repeating the opening composition at the
loop seam. It outputs WebM, MP4 and a still poster. The previous `momo-collage`
files remain intact. `ScrapbookBackdrop` now selects this new film on the
landing and sign-in screens; the existing scrim, pause control and reduced
motion behavior are retained.
