# MomoBot changelog

What changed in MomoBot production, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Each release is a `momobot-prod-YYYYMMDD-<sha8>` tag.
Entries are the titles of PRs merged to `main`. `deploy/momentum/ec2/release.sh <sha>` adds the next section
after the release passes `/health/ready` and the smoke check, and clears the Unreleased list it supersedes.
The Changed/Fixed/Security split is a keyword guess from each title.

The upstream DeerFlow history stays in [CHANGELOG.md](../CHANGELOG.md).

## [Unreleased]

## [momobot-prod-20261022-331f7395] - 2026-10-22

### Changed

- Gateway-only Brain snapshot mount, Oct 22 (#258)
- MomoBot mobile nav and session recovery, Oct 22 (#256)
- MomoBot changelog momobot-prod-20261022-526b957d, Oct 22 (#257)

## [momobot-prod-20261022-526b957d] - 2026-10-22

### Changed

- Align customer onboarding policy and isolate selected MCP discovery (#255)
- MomoBot changelog momobot-prod-20261022-99e617fd, Oct 22 (#254)

## [momobot-prod-20261022-99e617fd] - 2026-10-22

### Changed

- Add five Momo Max role-context bundles and synthetic acceptance contracts (#249)
- MomoBot changelog momobot-prod-20261022-e40c76fd, Oct 22 (#248)

## [momobot-prod-20261022-e40c76fd] - 2026-10-22

### Changed

- MomoBot onboarding: connect your tools on first login, Oct 22 (#245)
- MomoBot changelog momobot-prod-20261022-68a630c6, Oct 22 (#247)

## [momobot-prod-20261022-68a630c6] - 2026-10-22

### Changed

- MomoBot Max for the team, short sidebar, Easy/Medium/Hard switch, Oct 22 (#243)

## [momobot-prod-20261022-cfb3fba0] - 2026-10-22

### Changed

- Calm, smooth MomoBot: no static or glitch motion, Oct 22 (#239)

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
