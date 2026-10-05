# MomoBot Design C headshot

`momobot-design-c-v1.png` is the official headshot generated with the built-in
imageGen tool at Dillon's explicit request on October 3, 2026. It follows his
supplied Design C artwork: glossy royal-blue spherical head, two white pill eyes,
gold antenna tip, no pupils or mouth, and a warm cream paper background.

The immutable original is 1254 × 1254 PNG. Its SHA256 is
`d0134962bc825580e84dec00293f99cefc8499647a44e703e03aa1ec1167a4e2`.
This public artwork contains no credentials, client records, or private runtime
configuration. The generation prompt and reference receipts remain with the
private project handoff.

`scripts/package.cjs` copies these exact bytes to `assets/icon.png` for the
native connection screen and generates the standard macOS ICNS resolutions
with `sips` and `iconutil`. Scaling does not redraw or alter the character.
The existing web/PWA artwork has separate assets and deployment provenance.
