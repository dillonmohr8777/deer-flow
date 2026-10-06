# Cutover checklist: Mac mini to Lightsail

Exact order. Commands and detail for each step are in [RUNBOOK.md](RUNBOOK.md)
under the same number. `[D]` means Dillon runs it and it needs his live yes
(AWS, spend, credentials, DNS, Google, Slack, or the live Mac stack).

## Before the window (no downtime)

- [ ] 0 `[D]` `aws login`, `aws sts get-caller-identity` shows the right account
- [ ] Kit PR merged into `codex/momo-oct5-release-20261005` (or `MOMOBOT_REF` set to the PR branch)
- [ ] 1 `[D]` `ssm-push.sh --apply`, S3 bucket, IAM user `momobot-lightsail`
- [ ] 2 `[D]` Fill `REPLACE_ME` in `cloud-init.yaml`; create key pair, instance (xlarge_3_0, ubuntu_24_04, us-east-2a), static IP, attach, firewall 80/443 + 22 from your IP only
- [ ] 3 `[D]` SiteGround: `A momobot -> <static IP>`; `dig +short` returns it
- [ ] 4 `/var/log/momobot/cloud-init.done` exists; docker and aws installed
- [ ] 5 `[D]` `sudo aws configure`, then `bootstrap.sh`: images built, `.env` written, not started
- [ ] 6 `[D]` Google OAuth client: add `https://momobot.needmomentum.com/api/v1/auth/callback/google`
- [ ] 7 Mac-local model entries (`host.docker.internal`) decided; no default/fallback model depends on them

## Cutover window (about 10 to 15 minutes, announce first)

- [ ] 8 `[D]` Mac: `migrate-data.sh export` (Mac gateway now stopped)
- [ ] 8 `[D]` Mac: `migrate-data.sh mac-slack-off`
- [ ] 9 `[D]` Mac: `migrate-data.sh ship KEY IP`
- [ ] 10 `[D]` Box: `migrate-data.sh import FILE` (Slack off; `integrity_check: ok`)
- [ ] 11 Verify on the box before Slack:
  - [ ] `https://momobot.needmomentum.com/health` returns 200 (valid TLS)
  - [ ] `/login` shows Continue with Google; sign-in works for an existing user
  - [ ] A recent thread matches what the Mac showed
- [ ] 12 `[D]` Box: `migrate-data.sh slack-on`, then send one Slack message: exactly **one** reply

## After

- [ ] 13 `sudo systemctl start momobot-backup.service` prints `backup ok: s3://...`; object visible in S3
- [ ] 13 `health.sh` prints `"ok":true`; `systemctl list-timers 'momobot*'` shows health + backup timers (health.jsonl gains a line every 15 min = heartbeat)
- [ ] 13 `[D]` Lightsail AutoSnapshot enabled
- [ ] 13 `[D]` Port 22 closed (`put-instance-public-ports` with 80/443 only)
- [ ] 14 Mac stack stays stopped and untouched for 7 days; then remove the old redirect URI and delete the migration tarballs on both machines

## Rollback (any time in the window, or within 7 days)

- [ ] Box: `migrate-data.sh server-export` (stops, Slack off, writes `return-*.tgz`); skip if the box is unreachable
- [ ] Mac: `scp` it back, `migrate-data.sh mac-restore FILE`, `migrate-data.sh mac-slack-on`, `mac/restart.sh`
- [ ] Box unreachable? Stop the Lightsail instance BEFORE `mac-slack-on` (its Slack is still on, and two Socket Mode connections double-reply)
- [ ] DNS or team URL points back at the Mac; Slack is on in exactly one place
