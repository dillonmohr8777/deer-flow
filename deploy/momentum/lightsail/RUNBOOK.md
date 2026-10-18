# MomoBot prod on one AWS Lightsail instance

Moves `momobot-prod` from Dillon's Mac mini (OrbStack, Tailscale Funnel) to one
Lightsail Linux instance at `https://momobot.needmomentum.com`. Nothing here has
been run: no AWS resource exists, nothing has been spent. Short version of the
order is in [cutover-checklist.md](cutover-checklist.md).

Legend: **[Dillon runs / needs live yes]** touches AWS, DNS, Google, Slack or
the live Mac stack, so it is spend, a login, a credential or a production
change. Plain steps are file-only or read-only.

## Shape

| Piece | Choice |
|---|---|
| Instance | Lightsail Xlarge (4 vCPU / 16 GB / 320 GB), Ubuntu 24.04 x86_64, `us-east-2a`, name `momobot-prod` |
| Images | Built on the box from the release branch (`docker compose build`); the Mac's arm64 images are not reused. Repo is public, so no registry. Tag `lightsail-<sha9>`. |
| Compose | Same layers as the Mac: `docker/docker-compose.yaml` + `docker-compose.dood.yaml` + `mac/compose.funnel.yaml` (fixed subnet, realip), plus `vps/compose.public.yaml` (Caddy, 80/443, automatic TLS) and `lightsail/compose.caddy-ip.yaml`. Wrapper: `lightsail/up.sh`. Project name stays `momobot-prod`, so volume names match the Mac. |
| Data | SQLite stays (the Postgres migrator skips LangGraph checkpoints). Volumes `momobot-prod_gateway-data` (deerflow.db, users/, memory, `.jwt_secret`) and `momobot-prod_redis-data`, plus `config.yaml`, `extensions_config.json`. |
| Secrets | SSM Parameter Store `/momobot/prod/<VAR>` (SecureString). `bootstrap.sh` rewrites `/opt/momobot/.env` (root, mode 600) from it on every run. Never in git, chat or the migration tarball. |
| Sandbox | The gateway keeps using the box's own Docker socket (DooD, `AioSandboxProvider`). The separate pool in `~/code/_setup/momobot-standby/sandbox-computer` does not move. |
| Backups | Nightly `backup.sh` to a private S3 bucket (consistent SQLite snapshot) + Lightsail automatic snapshots. |
| Slack | Socket Mode runs in exactly one place. The tarball is imported with Slack **off**; `slack-on` on the box is the deliberate switch, after `mac-slack-off` on the Mac. |

## Things that will bite if missed

1. **Mac-local model endpoints.** The Mac `config.yaml` points several models at
   `host.docker.internal` (Ollama `:11434`, oMLX `:8100`, another service on `:4310`).
   Those do not exist on the box. `migrate-data.sh export` prints the line
   numbers. Before cutover decide, per entry, remove it, repoint it at a hosted
   provider, or accept it being dead, and make sure no default or fallback model
   is one of them. `OMLX_API_KEY` in `.env` is the same story.
2. **Mac-only paths** in `compose.admission-20261005.yaml` (`~/.momo/admission`,
   `agency-evals`, `momo-lobby-driver/notes`) are not part of this kit. The box
   runs without the admission overlay and the agency-evals mount. If the
   Command Center board needs them on the box, that is a follow-up.
3. **OIDC URLs in `config.yaml`** are the Tailscale hostname. `import` rewrites
   them to the new domain in the copy it installs; the Mac file is untouched.
4. **Lightsail has no instance IAM roles.** The box needs one scoped IAM user's
   access key (`iam-policy.json`) configured once with `sudo aws configure`
   (stored in `/root/.aws`, root-only). Use that user for nothing else.
5. **`cloud-init.yaml` as Lightsail user data.** Lightsail launch scripts are
   normally shell. Ubuntu images pass user data to cloud-init, so `#cloud-config`
   should work; if `/var/log/momobot/cloud-init.done` is missing after 5 minutes,
   SSH in and run the commands from the file by hand (all idempotent).
6. **The kit is on this PR's branch.** Merge the PR into
   `codex/momo-oct5-release-20261005` first, or set `MOMOBOT_REF` in
   `cloud-init.yaml` to `claude/lightsail-kit-20261006` for the first boot.
7. **SSH is closed in steady state.** Open 22 to Dillon's IP only for steps 5 to 11,
   then close it again (step 13).

## 0. AWS login [Dillon runs / needs live yes]

```bash
aws login                     # or: aws configure sso
aws sts get-caller-identity   # confirm the right account
export AWS_DEFAULT_REGION=us-east-2
```

## 1. Secrets, backup bucket, box credentials [Dillon runs / needs live yes]

```bash
cd deploy/momentum/lightsail

# SSM: dry run lists key NAMES only, then write.
./ssm-push.sh
./ssm-push.sh --apply

# Backup bucket: private, encrypted, 30-day expiry.
B=momentum-momobot-backups-$(aws sts get-caller-identity --query Account --output text)
aws s3api create-bucket --bucket "$B" --region us-east-2 \
  --create-bucket-configuration LocationConstraint=us-east-2
aws s3api put-public-access-block --bucket "$B" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-encryption --bucket "$B" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-bucket-lifecycle-configuration --bucket "$B" --lifecycle-configuration \
  '{"Rules":[{"ID":"expire-nightly","Status":"Enabled","Filter":{"Prefix":"nightly/"},"Expiration":{"Days":30}}]}'

# The one IAM user the box uses (read /momobot/prod SSM, write that bucket).
sed "s/BUCKET_NAME/$B/g" iam-policy.json > /tmp/momobot-policy.json
aws iam create-user --user-name momobot-lightsail
aws iam put-user-policy --user-name momobot-lightsail --policy-name momobot --policy-document file:///tmp/momobot-policy.json
aws iam create-access-key --user-name momobot-lightsail   # type it into 'aws configure' in step 5; never paste it in chat
rm /tmp/momobot-policy.json
```

The backup bucket will hold `.jwt_secret` and `users/`: keep it private. The
backup never contains `.env`.

## 2. Instance, static IP, firewall [Dillon runs / needs live yes: spend]

Edit `cloud-init.yaml` first: set `MOMOBOT_ACME_EMAIL` and `MOMOBOT_BACKUP_BUCKET`
(`$B` above). Confirm the bundle id, then create:

```bash
aws lightsail get-bundles --region us-east-2 \
  --query 'bundles[?cpuCount==`4` && ramSizeInGb==`16`].[bundleId,price,diskSizeInGb]' --output text

aws lightsail create-key-pair --key-pair-name momobot-prod --region us-east-2 \
  --query privateKeyBase64 --output text > ~/.ssh/momobot-prod.pem && chmod 600 ~/.ssh/momobot-prod.pem

aws lightsail create-instances --region us-east-2 \
  --instance-names momobot-prod --availability-zone us-east-2a \
  --blueprint-id ubuntu_24_04 --bundle-id xlarge_3_0 \
  --key-pair-name momobot-prod --ip-address-type ipv4 \
  --user-data file://deploy/momentum/lightsail/cloud-init.yaml \
  --tags key=app,value=momobot

aws lightsail allocate-static-ip --region us-east-2 --static-ip-name momobot-prod-ip
aws lightsail attach-static-ip   --region us-east-2 --static-ip-name momobot-prod-ip --instance-name momobot-prod
aws lightsail get-static-ip      --region us-east-2 --static-ip-name momobot-prod-ip --query staticIp.ipAddress --output text

# Firewall: 80/443 public. 22 only from your current IP, for the migration; closed again in step 13.
MYIP=$(curl -s https://checkip.amazonaws.com)
aws lightsail put-instance-public-ports --region us-east-2 --instance-name momobot-prod --port-infos \
  fromPort=80,toPort=80,protocol=tcp \
  fromPort=443,toPort=443,protocol=tcp \
  fromPort=443,toPort=443,protocol=udp \
  "fromPort=22,toPort=22,protocol=tcp,cidrs=$MYIP/32"
```

## 3. DNS [Dillon, SiteGround]

`A  momobot  ->  <static IP>`, TTL 300. If a `momobot` record already exists (the old
hermes-vps one), change it; do not add a second. Check: `dig +short momobot.needmomentum.com`.
Caddy cannot get its certificate until this resolves to the box.

## 4. First boot check

```bash
ssh -i ~/.ssh/momobot-prod.pem ubuntu@<static IP>
cat /var/log/momobot/cloud-init.done && docker --version && docker compose version && aws --version
```

## 5. Bootstrap (build + secrets) [Dillon runs / needs live yes: credentials]

On the box:

```bash
sudo aws configure                          # the momobot-lightsail key from step 1; region us-east-2
sudo cat /etc/momobot/bootstrap.env         # no REPLACE_ME left
sudo /opt/momobot/src/deploy/momentum/lightsail/bootstrap.sh
```

It checks out `MOMOBOT_REF`, writes `/opt/momobot/.env` from SSM, builds both
images (`lightsail-<sha9>`, the frontend takes a while), installs and enables the
systemd units, and **does not start** because config and data are not there
yet. Re-run it any time to deploy a new commit: bump `MOMOBOT_REF` or push to
that branch, run it again.

## 6. Google OAuth redirect URI [Dillon, Google Cloud console]

On the existing OAuth client add
`https://momobot.needmomentum.com/api/v1/auth/callback/google`. Keep the
Tailscale one until the rollback window closes (step 14). Consent screen stays in
Testing with the invited people as test users.

## 7. Decide the Mac-local models (see "Things that will bite")

Edit the Mac `~/momobot-prod/config.yaml` entries that use `host.docker.internal`
before export, or edit `/opt/momobot/config.yaml` on the box after import (step 10).

## 8. Export [Dillon runs / needs live yes: stops the Mac gateway]

Announce a short window (about 10 to 15 minutes, no chat runs). On the Mac:

```bash
cd ~/momobot-prod/src/deploy/momentum/lightsail      # or wherever this branch is checked out
./migrate-data.sh export        # stops momobot-prod-gateway, writes ~/momobot-prod/migrate/momobot-migrate-<ts>.tgz
./migrate-data.sh mac-slack-off # Slack off in the Mac config, so a later Mac restart cannot double-listen
```

## 9. Ship [Dillon runs]

```bash
./migrate-data.sh ship ~/.ssh/momobot-prod.pem <static IP>
```

## 10. Import and start on the box (Slack stays off) [Dillon runs / needs live yes]

```bash
sudo /opt/momobot/src/deploy/momentum/lightsail/migrate-data.sh import /opt/momobot/import/momobot-migrate-<ts>.tgz
```

Verifies the manifest, loads both volumes, installs the config with the OIDC URLs
rewritten and `channels.slack.enabled: false`, checks `PRAGMA integrity_check`
(must say `ok`), then starts the stack. `--force` replaces an existing volume
after saving a copy; `--no-start` stops before starting.

## 11. Verify before Slack

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://momobot.needmomentum.com/health        # 200
sudo /opt/momobot/src/deploy/momentum/lightsail/up.sh compose ps                        # all healthy
```

Then in a browser: `/login`, **Continue with Google**, sign in as a Momentum user
(existing account, no re-invite), open a recent thread and confirm it matches the Mac.

## 12. Slack switch [Dillon runs / needs live yes]

Only after step 8 `mac-slack-off` and step 11 pass:

```bash
sudo /opt/momobot/src/deploy/momentum/lightsail/migrate-data.sh slack-on
```

Verify **one** reply: send one message to the bot in Slack as Dillon
(`allowed_users`), expect exactly one answer. Two answers means the Mac is still
listening: `./migrate-data.sh mac-slack-off` and check that
`docker ps` on the Mac shows no `momobot-prod-gateway`.

## 13. Steady state

```bash
# backup: run once by hand, expect "backup ok: s3://..."
sudo systemctl start momobot-backup.service && journalctl -u momobot-backup -n 5 --no-pager
aws s3 ls s3://$B/nightly/

# health: first line has "ok":true once a backup exists
sudo /opt/momobot/src/deploy/momentum/lightsail/health.sh
systemctl list-timers 'momobot*'

# Lightsail daily snapshot [Dillon runs / needs live yes: spend]
aws lightsail enable-add-on --region us-east-2 --resource-name momobot-prod \
  --add-on-request 'addOnType=AutoSnapshot,autoSnapshotAddOnRequest={snapshotTimeOfDay=06:00}'

# close SSH [Dillon runs / needs live yes]
aws lightsail put-instance-public-ports --region us-east-2 --instance-name momobot-prod --port-infos \
  fromPort=80,toPort=80,protocol=tcp fromPort=443,toPort=443,protocol=tcp fromPort=443,toPort=443,protocol=udp
```

The "scheduler heartbeat" today is the health timer: a new line in
`/var/log/momobot/health.jsonl` every 15 minutes with `"ok":true`. The product
scheduler (`scheduler.enabled`) is `false` in the Mac config; if it is turned
on later, also confirm `up.sh compose logs gateway | grep -i scheduler` shows it
starting and claiming runs, and that it is enabled on the box only (the Mac
stack is stopped).

Reach SSH later without a standing hole: open 22 to your IP, work, close it, or
use the Lightsail browser SSH (alias `lightsail-connect`).

## 14. After cutover

Keep the Mac stack stopped, its volumes and Tailscale Funnel as they are, for 7
days (rollback path). Then remove the Tailscale redirect URI, decide on the Mac
volumes, and delete `~/momobot-prod/migrate/*.tgz` and
`/opt/momobot/import/*.tgz` (they contain `.jwt_secret` and user data).

## Rollback to the Mac [Dillon runs / needs live yes]

Within the window, with nothing lost since cutover:

```bash
# Box: stop, Slack off, write a return tarball with anything new
sudo /opt/momobot/src/deploy/momentum/lightsail/migrate-data.sh server-export
# Mac: pull it, restore the volumes, Slack back on, start
scp -i ~/.ssh/momobot-prod.pem ubuntu@<static IP>:/opt/momobot/import/return-<ts>.tgz ~/momobot-prod/migrate/
cd ~/momobot-prod/src/deploy/momentum/lightsail
./migrate-data.sh mac-restore ~/momobot-prod/migrate/return-<ts>.tgz
./migrate-data.sh mac-slack-on
~/momobot-prod/src/deploy/momentum/mac/restart.sh
```

If the box is unreachable, skip `server-export`: the Mac volumes still hold the
data as of export. Start the Mac with `mac-slack-on` + `restart.sh`; you lose only
what happened on the box. Point the `momobot` DNS record back at whatever fronts
the Mac, or tell the team to use the Tailscale URL again. Slack must be off on
the box (`slack-off`, or stop the instance) before the Mac turns it on.

## Restore the box from backup

```bash
aws s3 cp s3://$B/nightly/momobot-<stamp>.tgz /opt/momobot/import/
sudo /opt/momobot/src/deploy/momentum/lightsail/migrate-data.sh import /opt/momobot/import/momobot-<stamp>.tgz --force
```

Same tarball layout as a migration (gateway-data, config, extensions, manifest),
so `import` takes it directly. Slack comes back OFF; run `slack-on` when ready.

Or restore the Lightsail snapshot (console or `aws lightsail create-instances-from-snapshot`).
Rehearse the S3 path once on a throwaway box before relying on it.
