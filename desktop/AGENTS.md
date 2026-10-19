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
Ship with `npm run release` (fixed tag, never GitHub "latest"; writes the
download site's release.json, install.sh and a setup.sh pinning the ZIP and
installer SHA-256) only after the PR is agent-reviewed and Dillon approves;
deploying the site folder is what ships the update. Never hand-upload builds.
The local Tools panel exists only with `MOMOBOT_TOOLS=1`; the local settings
server rejects any request without the per-launch secret header. Smoke flags: `--smoke-profile <dir>` keeps a real session
for relaunch/download tests; `MOMOBOT_UPDATE_URL` reports the update check.

## Tools (src/tools)
Browse (Browserbase cloud or local Chrome profile over raw CDP), Fetch (Expand, public pages), Vault (Bitwarden CLI via the Keychain-backed `~/.local/bin/bw`) and Codes (TOTP, iMessage, Gmail). One registry (`tools.cjs`) feeds the Tools panel (`/tools` on the loopback settings server, menu Tools...) and the stdio MCP server (`src/tools/mcp-server.cjs`). The renderer still has no native bridge. Secrets are read in the main process only, typed over CDP after a domain lock (`policy.cjs`), redacted from outputs, and never take a tool argument. The ledger (`ledger.cjs`) holds item id, domain, action and time only. Google, Facebook and Apple are never opened or auto-filled in Browserbase. Live acceptance: `node scripts/e2e-tools.cjs`.

## Login submission guard, October 16, 2026
Credential submission requires an explicit native submitter in the credential field’s form. Re-read its effective live formAction (including overrides), verify the saved HTTPS domain and protected-site policy immediately before clicking, and refuse unknown implicit Enter submission. Keep synthetic changed-destination regression tests. This DOM guard does not establish protection against arbitrary page JavaScript.
