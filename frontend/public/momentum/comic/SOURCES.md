# Comic intro art

These are the panels and splash pages behind the front-door comic intro
(`components/momentum/momobot/comic-intro.tsx`) and the settled panel wall
(`comic-wall.tsx`). They were made on 2026-09-24 for Dillon's brief: "a marvel
comic book movie intro type of deal". The intro borrows the style of a
superhero-studio opening, but it carries no franchise characters, names or marks.

**How the art was made:**

- **Model:** GPT Image 2.5, called directly through the OpenAI API:
  - "Flare" (medium quality) for the 46 storm panels, including 2 calibration panels.
  - "Sunburst" (high quality) for the splash pages.
- **Character reference:** each prompt carried a reference render of the canon
  Momos (`momos/*.svg`: royal sphere, white pill eyes, grey antenna with a brass
  ball, ball hands).
- **Style bible:** modern superhero comic ink, halftone shading, royal blue and
  white with orange only on energy. No text, logos, bubbles, signatures or
  franchise characters.
- **Prompts and spend:** each image's prompt is kept with the source PNGs, and
  every call is logged in `spend.csv`, both in the build folder. The estimated
  total is $3.82.

**Review:**

- Every image was checked by eye, and suspects at full resolution.
- Five were rejected: three carried cursive signatures or four-finger glove hands
  (the shot list had asked for "a signed page"), one had a glove hand, and one had
  a handwriting-like squiggle.
- All five were regenerated with prompts for blank ruled pages and ball hands, and
  the replacements passed.
- The reject list is in the build folder's README.

**Files:**

- `<id>.webp` is the desktop variant: 640 px long edge for panels (q54), native
  1536 px for splashes (q56).
- `<id>.m.webp` is the phone variant: 400 px for panels, 1024 px for splashes.
  The intro picks it at 704 px wide and under.
- There's no EXIF or ICC metadata.
- `manifest.json` gives each image's kind, source size and mean luminance. The
  intro deals panels by shape and orders the flip storm light to dark by that
  luminance, so the run darkens with the blue wash instead of strobing.

**Build folder:** `Documents/Codex/2026-09-24/momo-marvel-intro/`. It has the
source PNGs (`art/`), the prompts, `spend.csv`, the conversion script
(`tools/webp.py`) and a flash check of the recorded intro (`tools/flashcheck.py`,
worst window 1 flash per second).
