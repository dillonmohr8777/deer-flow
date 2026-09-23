# MomoBot intro assets

All files here are Momentum's own artwork, copied and re-encoded on
2026-09-23 for the MomoBot front door (landing collage and sign in). No
client material, no photographs of real people, no third-party marks.
Re-encoding: Pillow 12.3, WebP, method 6. Total on disk about 0.95 MB.

## login-wave.webp (sprite, 5 frames of 360x262, alpha)

- Frames 0 to 3: `C:\Users\dillo\Documents\Qwen\block-shots\2026-09-23-momobot\cut\login-wave-0..3.png`
  (876x720 RGBA, four aligned cut-paper Momo wave frames; see
  `wave-preview.gif` in the same folder).
- The cream card strip under his hands in the source frames was removed
  (card-coloured pixels at and below row 564 set transparent, grown 1px), so
  the real sign-in sheet shows through and his fingers rest on its edge. Cropped
  to the fingertips (row 636), scaled to 360 wide, quality 86.
- Frame 4 (blink) is frame 0 with both eye pills painted in the sampled face
  blue and a cream closed-lid arc drawn on each, matching the closed eyes of
  `scene-sleep.png`. Row 233 of the sprite is the sheet edge line.

## collage/ (33 stills, max 900px wide, quality 78)

New MomoBot scenes, transparent cut-outs flattened onto newsprint `#efe9dc`:

- `scene-{celebrate,daily,idea,peek,pencil,point,rocket,sleep,thumbs,wave}.webp`
  from `C:\Users\dillo\Documents\Qwen\block-shots\2026-09-23-momobot\cut\scene-*.png`
  (native size, not upscaled).

Curated from the Creative Reuse Library
(`C:\Users\dillo\Documents\Codex\2026-09-14\giv\outputs\Creative-Reuse-Library`,
read via START-HERE-CLAUDE.md, REUSABLE.csv and HIGGSFIELD-GENERATIONS.json).
All three sources are Momentum 360's own brand deliverables:

- `still-*.webp` (16): Google AI Studio batch stills, 2026-09-07,
  `client-operations\clients\momentum-360\deliverables\2026-09-07-google-aistudio-batch\site\stills\momentum_*.png`:
  01*launch*{detail,hero,module}, 02*services*{detail,hero,props},
  03*momo_hero, 05_launch*{burst,hero} (Philadelphia at night),
  x1_momo_machine, x2_paper_city, x3_the_fold, x4_page_writes,
  x6_particles_cream, x7_bird_plate, x8_scrapbook_opener.
- `engraving-{philly,bird,botanical}.webp`: Momentum brand system v3,
  2026-09-08, `...\2026-09-08-momentum-brand-system-v3\assets\*-engraving.png`
  (generation prompts sit beside each file).
- `film-{parts,brain,twine,molecule}.webp`: single frames from Momentum's
  paper-craft films (`...\2026-09-09-paper-craft-brand-film\momentum-360-built-not-templated-2026-09-09.mp4`
  at 0s, 3.2s, 6.4s and `...\2026-09-10-paper-craft-anatomy-series\momentum-360-anatomy-of-a-lead-2026-09-10.mp4`
  at 0s), cropped to the top 760 of 1080 rows to drop the burned-in caption.

Skipped on purpose: the 2026-09-08 v3 3D mascots and the older bumper Momo
(off canon since the 2026-09-21 re-lock), client deliverables, headshots and
anything with a real person.
