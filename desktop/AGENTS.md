# MomoBot desktop

Use the existing private agency, app identity and persistent session partition.
Keep provider credentials server-side; the renderer has no native bridge.

Branding uses the immutable Design C PNG in `branding/`, with provenance in
`SOURCES.md`. Packaging copies exact source bytes to the connection-screen icon
and generates standard ICNS resolutions. Do not redraw the character.

Keep `package.json` and its lockfile versions aligned. Desktop-only releases
do not bump backend/Helm versions, activate the private agency or deploy web/PWA
assets. Run `npm run check`, `npm test`, packaging and hidden smoke checks.
Retain earlier releases and sessions. Distinguish ad-hoc signing from Developer
ID/notarization; release metadata must describe the actual source and signature.
