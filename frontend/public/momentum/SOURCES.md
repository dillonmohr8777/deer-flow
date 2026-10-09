# Momentum assets

- wordmark.png: unchanged exact Momentum artwork, copied from client-operations/clients/momentum-360/deliverables/2026-08-03-need-momentum-homepage-concepts/public/assets/brand/need-momentum-logo.png. Provenance documented in that deliverable's ASSET-SOURCES.md; original public Need Momentum website artwork.
- Colors and typography: C:/Users/dillo/Documents/Codex/momentum-design-system/tokens.css (September 5, 2026).
- Archivo Black and Nunito Sans: Google Fonts official CSS API, self-hosted unchanged font files. These are the existing Momentum brand families.
- Fraunces (400/700) and Caveat (400): Google Fonts CSS2 API, latin subset,
  self-hosted unchanged woff2. Both OFL 1.1. Added 2026-09-22 — fonts.css had
  declared them since 2026-09-21 but the files were never committed, so the
  serif and script voices were silently falling back to system faces on every
  surface that used them.
- No code/mono face is shipped. `--m-font-mono` is a system stack by choice;
  see the note on it in fonts.css.
- collage-navy.png: torn navy paper collage, the undegraded fill for the
  cut-paper headline. Generated 2026-09-22 with google/gemini-3-pro-image via
  OpenRouter, then post-processed locally: downscaled 1408x768 to 704x384, and
  every highlight clamped to a 4.5:1 contrast floor against cream. The raw
  generation had cream hairlines at 0.91:1 where torn edges lifted, which would
  have put light speckles inside the letterforms. Measured after processing:
  mean 13.02:1, worst pixel 4.52:1, zero pixels below AA large. No text, marks
  or third-party imagery in the generated content.
- `momos/*.svg`: the canon Momo crew, hand-authored vector written by
  `scripts/generate-momos.mjs` (re-run it rather than editing the files). Body
  geometry is momo-mark.svg and the 2026-09-22 celebration paper kit, per the
  canon Dillon re-locked 2026-09-21: royal sphere, white pill eyes, grey
  hardware, gold only on the antenna ball and one rivet. Each role adds one grey
  tool. No generated imagery, no third-party artwork; the manifest test pins
  every file to the canon palette and 8 KB.
- momo-mark.svg: newly authored flat vector interpretation of the blue face, white pill eyes and yellow antenna in Dillon's existing 29-second `C:/Users/dillo/Downloads/momentum-momo.mp4` ("Momentum built a bot. It watches the money."). This is a new interpretation from the inspected film, not a recovered original SVG. It is used as a brand character, not an agent activity indicator. Paper depth is informed by the recovered `Momo - First Assignment.dc.html` and `Momo - Living Portfolio Film.dc.html` references; no claims from the films are copied into product state.
- Appearance treatments (space/future/retro), added 2026-09-23. All three via Google Fonts CSS2 API, latin subset, self-hosted unchanged woff2, OFL 1.1:
  - space-mono.woff2 (16,520 bytes, weight 400) and space-mono-bold.woff2 (16,724 bytes, weight 700): Space Mono. Used for the "space" treatment's headings and code (`--space-font` in `src/styles/space.css`).
  - orbitron-bold.woff2 (6,528 bytes, weight 700): Orbitron. Used for the "future" treatment's headings only (`--future-font` in `src/styles/future.css`); body text stays on the existing self-hosted Nunito Sans.
  - press-start-2p.woff2 (12,512 bytes, weight 400, the only weight Press Start 2P ships): Press Start 2P. Used for the "retro" treatment's headings, labels and code (`--retro-pixel-font` in `src/styles/retro.css`); long body text stays on the existing self-hosted Nunito Sans for readability.
