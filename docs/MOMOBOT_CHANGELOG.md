# MomoBot changelog

What changed in MomoBot production, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Each release is a `momobot-prod-YYYYMMDD-<sha8>` tag.
Entries are the titles of PRs merged to `main`. `deploy/momentum/ec2/release.sh <sha>` adds the next section
after the release passes `/health/ready` and the smoke check, and clears the Unreleased list it supersedes.
The Changed/Fixed/Security split is a keyword guess from each title.

The upstream DeerFlow history stays in [CHANGELOG.md](../CHANGELOG.md).

## [Unreleased]

## [momobot-prod-20261022-76744ed9] - 2026-10-22

### Changed

- Momo Daily published and built to rank, Oct 22 (#235)
- Sean's MomoBot access: Easy, exec and Google auto-join on invite, Oct 22 (#231)
- MomoBot base and MomoBot Max client tiers, Oct 22 (#233)
- Release script: smoke the real container names, Oct 22 (#232)
- One-command MomoBot prod release, Oct 21 (#228)
- Bump katex from 0.16.28 to 0.18.2 in /frontend (#224)
- Fictional client name in tests, Oct 21 (#229)
- Placement extension mount on EC2, Oct 21 (#226)
- MomoBot 1Password logins, Oct 21 (#223)
- Bump aiohttp from 3.14.3 to 3.14.4 in /workers/browser-teams/python (#221)
- Bump certifi from 2026.7.22 to 2026.10.19 in /workers/agno-team (#220)
- Run cost admission on the effective model, Oct 21 (#217)
- Patch Node runtimes, Oct 21 (#222)
- Sandbox works on OrbStack, Oct 19 (#174)
- Bump pillow from 12.3.0 to 13.0.0 in /workers/browser-teams/python (#182)
- Bump mcp from 1.28.1 to 1.30.0 in /backend (#180)
- Bump @modelcontextprotocol/sdk from 1.31.0 to 1.32.1 in /workers/inngest-team (#181)
- Keep channel guide under the size check, Oct 21 (#218)
- Employee Academy and private inbox acceptance, Oct 21 (#214)
- Slack posts never double-send, Oct 21 (#216)
- AWS headroom, Oct 21 (#215)
- Keep shared chat events visible, Oct 21 (#213)
- Host-only Browserbase vault access, Oct 21 (#211)

### Fixed

- Approvals race test on a real pool, Oct 21 (#227)
- Broker unit snap fix, Oct 21 (#225)
- Fictional names in public test fixtures, Oct 21 (#219)

## [momobot-prod-20261021-43f1453f] - 2026-10-21

### Changed

- Bump next from 16.3.6 to 16.3.8 in /frontend (#205)

### Fixed

- Fix Academy media playback, Oct 21 (#210)
- Restore Momo Daily portraits and Academy films, Oct 21 (#208)

### Security

- Patch runtime security dependencies, Oct 21 (#209)

## [momobot-prod-20261021-d8d7dd4b] - 2026-10-21

### Changed

- Account-manager public research tools, Oct 21 (#207)

### Fixed

- Fix AM plugin status and multi-step runs, Oct 21 (#206)

## [momobot-prod-20261021-7c53741b] - 2026-10-21

### Changed

- Patch production dependencies, Oct 21 (#204)
- VHIN placement desk and mobile readiness, Oct 21 (#202)
- Budget memory extraction, Oct 21 (#203)

## [momobot-prod-20261021-3056b389] - 2026-10-21

### Changed

- Readable text in every theme, Oct 20 (#200)
- Mobile setup and mode access, Oct 21 (#201)
- Slack works for everyone on the roster, Oct 20 (#194)
- Prepare isolated memory gateway image, Oct 21 (#199)
- Read saved Brain context on EC2, Oct 21 (#196)
- Role tiers, client MomoBot, MomoBot Max, Oct 20 (#192)
- Back up Redis and EC2 recovery files, Oct 21 (#197)
- Preserve Mac-final backup originals, Oct 21 (#195)
- Short MomoBot sidebar, no OpenAI crew, Oct 20 (#193)
- MomoBot on EC2, Oct 20 (#191)
- Desktop runner serves several workspaces, Oct 20 (#190)
- Slack desktop jobs and approve command, Oct 20 (#189)
- Desktop runner CSRF pair, Oct 20 (#186)
- MomoBot iOS shell, Oct 20 (#184)
- Kit video titles, Oct 20 (#183)
- MomoBot desktop 0.3.1 team release, Oct 19 (#173)
- MomoBot About and Agents lineup, Oct 20 (#177)
- MomoBot Slack AM roster and desktop bridge, Oct 20 (#175)
- Fleet claim route and project jobs, Oct 20 (#178)
- MomoBot QA CAPTCHA solver on, Oct 20 (#176)
- Update Momo release review, Oct 8 (#154)
- Agency lessons skill, Oct 6 (#147)

### Fixed

- Memory profile compatibility fix, Oct 21 (#198)
- Preserve cloud restore mounts, Oct 20 (#188)
- Restore slash command parity, Oct 20 (#187)
- Prod parity fixes and DM About, Oct 20 (#179)
