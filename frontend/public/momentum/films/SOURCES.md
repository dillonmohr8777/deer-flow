# Momo films

Momo films were made 2026-09-23. The character reference is Dillon's own Momo clip. Other clips use Higgsfield Seedance 2.5 (omni_reference, 720p, no audio), then local ffmpeg WebM (VP9), MP4 (H.264), and WebP poster exports.

`momo-intro` is a 10-second silent scrapbook montage: eight multi-image plates generated with OpenAI `gpt-image-2.5-sunburst`, composited locally with blue/yellow particles and the exact Momo mark, then resolved into the Higgsfield intro source below. The generated plates, prompts, source hashes, render script, and QA are in `C:\Users\dillo\Documents\Codex\2026-09-23\we-ll-see-how-good-you\work\momo-collage`.

| Name          | Job                                  | Used on                                   |
| ------------- | ------------------------------------ | ----------------------------------------- |
| momo-intro    | 1ae167cf-fa06-497f-a2ad-c9b39859c4dd | landing hero (plays once)                 |
| momo-hello    | 76660308-af3e-4927-98ac-15921cc87ca7 | sign in (loop)                            |
| momo-thinking | 72154ca3-2120-4ca0-b54d-74a8160645e5 | chat "working" row (loop)                 |
| momo-daily    | f4079128-864e-4012-958f-1cccc3d1c22a | Momo Daily masthead and empty lead (loop) |
| momo-pencil   | 0e6214d7-2e5b-432f-9364-82e644a04cbf | empty chat (loop)                         |
| momo-crew     | 19219217-75f8-42b8-b55a-6d278573b19a | Agents page (plays once)                  |
| momo-done     | 8fd685ce-09ed-461b-bff6-26f6b7a100ce | not placed yet                            |

All films render through `src/components/momentum/momo-film.tsx`. They are muted, never preloaded, and show only the poster when motion is off.
