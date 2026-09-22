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
