# MomoBot cloud hosting plan (Oct 20 2026)

Dillon, Oct 20: move MomoBot prod off the Mac mini to secure cloud hosting so it runs 24/7. The Max Plus ad
says "always on 24/7, securely hosted in the cloud, credentials locked down", and that has to be true before a
client sees it. This plan builds on the existing kit in this folder ([RUNBOOK.md](RUNBOOK.md),
[cutover-checklist.md](cutover-checklist.md)), adds a staging box, alerting, the desktop bridge and the
Mac-only pieces the kit skipped, and lists every cost for Dillon's yes. Nothing in it has been run or bought.

## Decision: AWS Lightsail, existing account

- **Why Lightsail:** the account (`009688440435`, us-east-2) is already Dillon's and the CLI login works. It has flat
  monthly pricing with transfer included, and the kit is already written for it. Vercel and Cloudflare can't run the
  Docker-socket sandbox, and Fly/a raw VPS would mean a new paid account plus rewriting the kit.
- **Prod:** one `xlarge_3_0` (4 vCPU, 16 GB, 320 GB SSD, Ubuntu 24.04). Today's Mac prod uses about 1 GB for the stack
  plus about 570 MB per live chat sandbox. 16 GB covers around 20 concurrent sandboxes for 81 staff, and the 12 GB
  sandbox image plus 30 GB of images fit on the disk with room to spare.
- **Staging:** one `large_3_0` (2 vCPU, 8 GB, 160 GB) running the same compose, its own SSM path, no Slack and a
  `staging.momobot.needmomentum.com` name. It can be stopped between releases. Lightsail still bills a stopped
  instance, so stop means delete-and-recreate from the latest snapshot.

| Item | Monthly (USD, live `get-bundles` Oct 20) |
|---|---|
| Prod instance `xlarge_3_0` | 84.00 |
| Staging instance `large_3_0` (if always on) | 44.00 |
| Snapshots (prod auto daily, about 40 GB used, at $0.05/GB) | about 2 to 5 |
| S3 nightly backups (under 5 GB, SSE) | under 1 |
| SSM Parameter Store (standard SecureString) | 0 |
| Static IPs (attached) | 0 |
| **Total** | **about $130/month** with staging always on, **about $90/month** with staging on demand |

These are purchases on Dillon's account, so they need his yes. **Ask: approve about $90/month for prod and up to
$44/month for staging.**

## Security

- **Secrets:** SSM Parameter Store `/momobot/{prod,staging}/<VAR>` (SecureString, AWS-managed KMS key).
  Change from the kit: `bootstrap.sh` writes the env file to `/run/momobot/env` (tmpfs, root 600). It is gone on
  reboot and refetched by the systemd unit at start, so no `.env` sits on the disk and none is ever in git, chat or
  the migration tarball. The GitHub read token, Slack tokens and model keys all move this way.
- **IAM:** one IAM user per box (Lightsail has no instance roles), limited to `ssm:GetParameter*` on its own path
  and `s3:PutObject/GetObject/ListBucket` on its own backup bucket (`iam-policy.json`). It holds no console access
  and is used for nothing else. Dillon's admin login is never put on a box.
- **Network:** only 80/443 are public, served by Caddy with automatic TLS. SSH (22) opens to Dillon's IP for
  setup and closes after. The gateway, Redis and sandboxes stay internal. Docker socket proxy and a non-root
  gateway (SEC-003) land before cutover, since the box is internet-facing.
- **Slack:** Socket Mode, so the box connects out to Slack and nothing inbound needs a signing secret. The
  `trusted_app_ids` check and `allowed_users`/roster gate move with the config unchanged. If Slack ever switches to
  HTTP events, verify `X-Slack-Signature` (signing secret in SSM) before anything else runs.
- **Per-user scope:** the database, users/, memory and roles move as-is (SQLite plus volumes). The authorization
  config (teammate allow-list, `fleet:work` deny, GitHub write deny) is the same file. The cutover probes below
  prove it.
- **Admission and guards:** today these are bind mounts from the Mac (`~/.momo/admission`, `momo_guard.py`,
  `momo_protocol.py`, the brain read-only adapter, skills from a worktree). On the box they are baked into the image
  or copied under `/opt/momobot` by `bootstrap.sh`, so nothing depends on the Mac.
- **Audit:** gateway audit events stay in the DB. Caddy access logs and `journalctl` go to `/var/log/momobot`, kept
  30 days. AWS CloudTrail (on by default, 90 days) records every IAM, SSM and Lightsail call.
- **Backups and restore:** nightly consistent SQLite snapshot plus volumes to S3 (SSE, versioned, 30-day lifecycle),
  and Lightsail daily auto-snapshot. A restore drill on staging before cutover is part of the test plan.

## 24/7 operation

- **Restart:** Docker `restart: unless-stopped`, plus a systemd unit that starts the stack on boot after the secrets
  fetch.
- **Health:** `health.sh` runs on a 15-minute systemd timer (gateway `/health`, chat probe, disk, memory).
- **Alerting to Dillon** (no new paid account):
  - Lightsail metric alarms for CPU, status-check failure and burst capacity, using an email and SMS contact
    method to Dillon.
  - A scheduled GitHub Actions workflow (Actions run on this fork again) that curls `https://momobot.needmomentum.com/health`
    every 15 minutes and emails on failure.
- **Deploys:** images are built on the box from a tagged main commit (`main-<sha8>`), and the previous tag is kept.
  Rollback is setting the tag in `/opt/momobot/release` and running `up.sh`, about 1 minute. Every release goes to
  staging first, then prod.

## Migration

1. Data: `migrate-data.sh export/ship/import` (deerflow.db, users/ including memory and USER.md, `.jwt_secret`,
   SOUL.md, threads). `integrity_check` must pass.
2. Brand kit: copy `~/momobot-prod/brand` to `/opt/momobot/brand` (read-only mount).
3. Config: remove the Mac-only model entries (`host.docker.internal` Ollama/oMLX) and keep the Claude defaults.
   OIDC and redirect URLs move to `momobot.needmomentum.com`.
4. Slack: Socket Mode, so only the running place changes. Switch Slack off on the Mac (`mac-slack-off`), then on
   the box (`slack-on`). The app needs no URL change.
5. Desktop app: point `release.json`/`setup.sh` and the default workspace URL at `https://momobot.needmomentum.com/workspace`.
   Installed apps keep working on the old URL until they update, and the Mac's Funnel URL then redirects for 7 days.
6. Desktop bridge: the Mac runner (`scripts/momobot_desktop_runner.py`) polls the cloud gateway's fleet claim endpoint
   with a per-host internal delegation key. Traffic is outbound only from the Mac, with no inbound port. With the Mac
   off, desktop-lane jobs wait in the queue until it comes back, and everything else runs in the cloud.
7. The Mac can be fully off: the only Mac dependency left is the optional desktop-lane runner.

## Cutover test plan (all must pass on staging, then on prod before Slack goes on)

- Health 200 over valid TLS, sign-in with Google and local login, and a recent thread matches the Mac.
- `sec_check` as a non-admin:
  - chat runs on Haiku and Opus, with write_file and download returning 200;
  - bash is not offered;
  - a blocked model, `fleet:work` and the docs return 403/404;
  - admin sees all 36 models.
- Slack probe (`scope_probe`): Dillon and Melissa Rigby are admitted, everyone else is ignored, and a bot_id
  post from an untrusted app is ignored.
- Red-team re-run: prompt-injection set from a teammate identity (scope escalation, other-client data, tool
  requests), with zero escalations.
- The claude-security scan on the release commit has no open critical or high finding.
- `/workspace/lineup` and `/workspace/about` load, videos stream (206) and no `$` appears. A GitHub repo list
  returns 58.
- Restore drill: restore last night's S3 backup onto staging and repeat the first check.

## Needs Dillon

1. **Yes on spend:** about $90/month for prod plus up to $44/month for staging (above).
2. **DNS:** add `A momobot` (and `staging.momobot`) at SiteGround pointing to the static IPs, or let me do it if a
   SiteGround login exists in Bitwarden.
3. **Google OAuth:** add the new callback URL to client `momobot-510021`, from the trusted Chrome profile.
4. **Cutover window:** a 15-minute slot to announce to the team.
