# MomoBot changelog

What changed in MomoBot production, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Each release is a `momobot-prod-YYYYMMDD-<sha8>` tag.
Entries are the titles of PRs merged to `main`. `deploy/momentum/ec2/release.sh <sha>` adds the next section
after the release passes `/health/ready` and the smoke check, and clears the Unreleased list it supersedes.
The Changed/Fixed/Security split is a keyword guess from each title.

The upstream DeerFlow history stays in [CHANGELOG.md](../CHANGELOG.md).

## [Unreleased]

## [momobot-prod-20261027-0cae83ee] - 2026-10-27

### Changed

- Keep setup and reconnects recoverable, Oct 27 (#342)
- MomoBot changelog momobot-prod-20261026-f3e24b62, Oct 26 (#341)

## [momobot-prod-20261026-f3e24b62] - 2026-10-26

### Changed

- Main test triage, Oct 26 (#338)

### Fixed

- MomoBot AM approvals tool fix, Oct 26 (#340)

## [momobot-prod-20261024-9f326b4c] - 2026-10-24

### Changed

- Staff work project picker, Oct 24 (#324)
- MomoBot changelog momobot-prod-20261024-93d29084, Oct 24 (#323)

## [momobot-prod-20261024-93d29084] - 2026-10-24

### Changed

- Scope client inbox context, Oct 24 (#319)
- Allow scoped project evidence reads in account-manager work (#320)
- Keep workspace profiles from falling back to shared USER text (#321)
- MomoBot changelog momobot-prod-20261024-ce8e9c67, Oct 24 (#318)

### Fixed

- Normalize the client role check and restore locked formatting (#322)

## [momobot-prod-20261024-ce8e9c67] - 2026-10-24

### Changed

- Validate explicit client links for account project evidence (#317)
- Give account managers scoped client context and request history (#316)
- MomoBot changelog momobot-prod-20261024-94e99a44, Oct 24 (#315)

## [momobot-prod-20261024-94e99a44] - 2026-10-24

### Changed

- Bound portal drafting to the requested facts and deliverable (#314)
- MomoBot changelog momobot-prod-20261024-a2ae200a, Oct 24 (#313)

## [momobot-prod-20261024-a2ae200a] - 2026-10-24

### Changed

- MomoBot changelog momobot-prod-20261024-5c144f5b, Oct 24 (#311)

### Security

- Attribute client-portal draft saves to the authenticated staff actor (#312)

## [momobot-prod-20261024-5c144f5b] - 2026-10-24

### Changed

- Keep client-portal drafts proportional to the request (#310)

### Fixed

- Repair baseline gateway and subagent test fixtures (#308)

## [momobot-prod-20261023-ff8263f9] - 2026-10-23

### Changed

- MomoBot changelog momobot-prod-20261023-749fd34d, Oct 23 (#275)
- Client workspace readiness, Oct 23 (#263)
- Per-agent subagent model, Oct 22 (#264)
- Release prunes old images, Oct 23 (#276)

### Fixed

- Retain isolated test fixes, Oct 23 (#278)
- Phone install hint and landing fixes, Oct 22 (#253)

## [momobot-prod-20261023-749fd34d] - 2026-10-23

### Changed

- WSL bridge env for EC2, Oct 23 (#274)
- Changelog backfill, Oct 23 (#271)
- MomoBot changelog momobot-prod-20261022-aaa418a7, Oct 22 (#270)

## [momobot-prod-20261022-aaa418a7] - 2026-10-22

### Changed

- Paid admission ceiling $100, Oct 23 (#269)
- MomoBot changelog momobot-prod-20261022-ae496b71, Oct 22 (#268)

### Fixed

- Fix saved Brain snapshot generation publication and reload (#267)

## [momobot-prod-20261022-ae496b71] - 2026-10-22

### Changed

- MomoBot changelog momobot-prod-20261022-207ab8a7, Oct 22 (#265)

### Security

- Add default-disabled authenticated WSL diagnostic exchange (#266)

## [momobot-prod-20261022-207ab8a7] - 2026-10-22

### Changed

- Move agent read config lookups off event loop (#262)
- Preserve complete Twin profiles within an 8 KiB prompt budget (#260)
- Release script refuses process substitution, Oct 22 (#261)
- MomoBot changelog momobot-prod-20261022-331f7395, Oct 22 (#259)

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

## [momobot-prod-20261022-d2fd3334] - 2026-10-22

### Changed

- Private workspace shows its own name, Oct 22 (#241)
- Paper fonts in dark mode, Oct 22 (#242)

## [momobot-prod-20261022-0f485d40] - 2026-10-22

### Changed

- Daily search verification and takeaway bullets, Oct 22 (#238)
- MomoBot changelog momobot-prod-20261022-cfb3fba0, Oct 22 (#240)

## [momobot-prod-20261022-cfb3fba0] - 2026-10-22

### Changed

- Calm, smooth MomoBot: no static or glitch motion, Oct 22 (#239)

## [momobot-prod-20261022-76744ed9] - 2026-10-22

- Momo Daily published and built to rank, Oct 22 (#235)
- Sean's MomoBot access: Easy, exec and Google auto-join on invite, Oct 22 (#231)
- MomoBot base and MomoBot Max client tiers, Oct 22 (#233)
- Release script: smoke the real container names, Oct 22 (#232)
- One-command MomoBot prod release, Oct 21 (#228)
- Bump katex from 0.16.28 to 0.18.2 in /frontend (#224)
- Fictional client name in tests, Oct 21 (#229)
- Placement extension mount on EC2, Oct 21 (#226)
- Approvals race test on a real pool, Oct 21 (#227)

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
