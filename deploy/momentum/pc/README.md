# MomoBot prod on the PC WSL host (since Oct 29, 2026)

AWS paused the EC2 project when it hit its monthly spend limit, so prod moved to the Windows PC's WSL Ubuntu
host. Same images and the same compose layers as the Mac Funnel stack (base + dood + `mac/compose.funnel.yaml`)
plus the EC2 mount layer (`ec2/compose.ec2.yaml`, copied to `/opt/momobot/compose.pc.yaml`; the paths are
identical). No AWS anywhere: no SSM, no S3, no Caddy on the host.

```
browser -> GCE e2-micro "momobot-front" (static IP, Caddy TLS for the domain, front/Caddyfile)
        -> Tailscale Funnel on the PC (:8443, unattended mode)
        -> nginx 127.0.0.1:2026 in WSL -> gateway / frontend / redis
```

`front/Caddyfile` is a template: the live copy lives in the VM's `caddyfile` metadata with
`MOMOBOT_ORIGIN` (Funnel host:port), `MOMOBOT_ORIGIN_SNI` (Funnel host) and `MOMOBOT_FRONT_SSLIP`
filled in. `front/startup.sh` installs Caddy and reloads it whenever that metadata changes.

## Layout on the host (`/opt/momobot`)

Same as the EC2 box (see `../ec2/README.md`): `src` (checkout at the release SHA), `config.yaml`,
`extensions_config.json`, `frontend.env`, `.env` (mode 600, app secrets, never in Git), `data/`, `code/`,
`extensions/placement`, `brain-snapshot/` (root 0700). Plus:

- `pc-up.sh`: start or restart (never builds), waits for `/health`. It also re-privatizes the Brain Forge and
  WSL bridge trees in the gateway volume: Brain Forge refuses group- or world-readable ledgers, and a restore
  widens modes, which silently keeps the Slack channel from starting.
- `secrets/backup.key` (backup encryption key, also kept in the password manager) and
  `secrets/op-service-account.token` (host-only, never in the app env).
- `ops/watchdog.sh` + `momobot-watchdog.timer`: every 2 minutes; two `/health` misses in a row restart
  `momobot.service`. A `MAINTENANCE` file in `/opt/momobot` suppresses restarts during planned work.
  Log: `/var/log/momobot/health.jsonl`; status word: `/run/momobot-health`.
- `ops/release.sh`: the one-command release (below). `ops/backup-fresh.sh` + `momobot-backup-fresh.timer`: hourly at :20,
  emails the operator when the newest backup is older than 14 h (Monitoring).
- Install after a checkout: `install -m 755 deploy/momentum/pc/{backup,watchdog,release,backup-fresh}.sh /opt/momobot/ops/`,
  `install -m 755 deploy/momentum/pc/pc-up.sh /opt/momobot/pc-up.sh`, the units in `systemd/` to `/etc/systemd/system/`, then
  `systemctl daemon-reload`. Do this at every release, so the host never runs scripts that are not in Git (diff them first:
  `diff deploy/momentum/pc/backup.sh /opt/momobot/ops/backup.sh`). `pc-up.sh` uses `pc/nginx-realip.conf`, so install it only
  once `src` is checked out at a commit that contains this directory.
- `ops/backup.sh` + `momobot-backup.timer`: 03:30 and 15:30 ET. Online-safe SQLite snapshot
  (`../backup_volume.py`), config, extensions, redis RDB and the data/code mounts, AES-256 (openssl, pbkdf2),
  decrypted and listed as a read-back before it counts. Keeps 7 in `/opt/momobot/backups`. An operator
  machine copies each new one to object storage and checks the hash.

## Boot

`momobot.service` is enabled (WSL runs systemd). Windows starts WSL at boot with no logon through an S4U
scheduled task (`wsl.exe -d Ubuntu -u root -- systemctl start docker momobot`), and Tailscale runs unattended,
so the Funnel answers before anyone signs in.

## Build and release

```sh
cd /opt/momobot/src && git fetch && git checkout --detach <sha>
sudo MOMENTUM_GATEWAY_IMAGE=deer-flow-gateway:main-<sha8> MOMENTUM_FRONTEND_IMAGE=deer-flow-frontend:main-<sha8> \
  MOMOBOT_ENV_FILE=/opt/momobot/.env deploy/momentum/lightsail/up.sh build
sudo /opt/momobot/ops/release.sh --dry-run <sha>     # prints the plan, changes nothing
sudo /opt/momobot/ops/release.sh <sha>               # add --prune to drop older images (keeps the last 2 tags)
```

`release.sh` runs `backup.sh` first and stops if it fails, creates `MAINTENANCE` (the watchdog stands down), switches both
image tags in `.env`, runs `pc-up.sh`, polls `/health/ready` for up to 3 minutes and, on any failure, puts the previous tags back,
re-runs `pc-up.sh` and polls again (exit 1 = rolled back and healthy, exit 2 = rollback also failed). `MAINTENANCE` is always
removed on exit. Releasing the tags that are already running is a no-op. Every release appends a line to
`/opt/momobot/release.log`. Tested by `backend/tests/test_momentum_pc_release.py` (happy path, failed backup, failed `pc-up`,
readiness timeout, no-op, dry run, prune).

`../ec2/release.sh` targets the old EC2 box over SSH and does not apply here.

## Rollback

Automatic: `release.sh` already reverts to the previous tags when the new release does not become ready.

Manual (a release that started fine but is wrong): run `release.sh` with the previous sha. The previous images are still on the
host because pruning always keeps the newest two tags (the one running and the one before it); never `docker image prune -a` or
`docker rmi` them by hand.

```sh
tail -3 /opt/momobot/release.log                     # shows "old -> new"
sudo /opt/momobot/ops/release.sh <previous-sha>      # backs up, switches both tags back, waits for /health/ready
```

If data was written by the bad release and the schema moved forward, restore the pre-release backup instead (Restore, below);
`release.sh` took it just before switching, so it is the newest archive.

## Restore

Decrypt with `openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass file:KEY -in momobot-<stamp>.tgz.enc | tar xzf -`,
check `MANIFEST.sha256`, extract `gateway-data.tgz` into an empty `momobot-prod_gateway-data` volume, copy
`redis.rdb` into the redis volume as `dump.rdb`, then run `pc-up.sh` (it restores the private modes).

### Restore rehearsal and recovery time

`restore-rehearsal.sh` proves the newest archive restores: it checks the archive against its receipt, decrypts it, verifies
`MANIFEST.sha256`, restores into scratch volumes, starts a second gateway on `127.0.0.1:2927` (internal Docker network with no
egress, Slack and the scheduler switched off, dummy app env, never the prod project or volumes), compares row counts with prod,
prints a timing table and removes everything it created. Run it from `/opt/momobot/src/deploy/momentum/pc/` with `sudo`, never while
a backup is running (it refuses).

Measured Oct 30, 2026 on the PC host, archive of 579 MB, 2.3 GB gateway volume:

| step | seconds |
| --- | --- |
| verify archive against receipt | 5.7 |
| decrypt and extract | 5.9 |
| MANIFEST.sha256 check | 4.1 |
| restore into scratch volumes | 15.7 |
| start stack | 1.2 |
| gateway to `/health` 200 | 22.3 |
| total | 55.8 |

Measured RTO for restoring data and starting the app on a host that already has Docker, the images and the kit: **about 1 minute**.
A full host loss adds what is not measured here: getting a host, Docker, the images (built or loaded) and the app env. The standby plan is the operator
runbook `FAILOVER.md` (kept with the operator notes, not in Git). Row counts in the restored copy trailed prod by the activity since the
backup (2 threads, 2 runs), as expected. Repeat the rehearsal monthly and after any change to `backup.sh`.

## Monitoring

- Google Cloud uptime checks (60 s, six regions, SSL validation on): one on the public domain `/health` and one on the front's
  sslip hostname. Alert policy "MomoBot is down (front /health failing)" fires when either fails from 2 or more regions for 3 minutes.
- Alert policy "MomoBot TLS certificate expires in under 21 days": the uptime check's `time_until_ssl_cert_expires` below 21.
  Caddy renews at 30 days, so this only fires when renewal is broken.
- All policies notify the same email channel in the project.
- Backup freshness: `ops/backup-fresh.sh` (hourly, `momobot-backup-fresh.timer`) emails when the newest PASS receipt is older than
  14 hours (backups run every 12 h), at most once per 6 h. Settings (`ALERT_TO`, `COMPOSIO_ACCOUNT`) live in
  `/opt/momobot/ops/backup-fresh.env`, outside Git. The PC has no `gcloud`, so this watches the local archive only. The offsite copy
  is made by an operator machine; `backup-fresh.sh --gcs` (with `BUCKET` set) checks the newest object there and must run where
  `gcloud` is logged in.
- Test the alert: `sudo /opt/momobot/ops/backup-fresh.sh --threshold-hours 1` (sends one email, then stays quiet for 6 h).

## Holding page

When the PC, the Funnel or the app is down, the front answers 503 with a small branded page (`front/Caddyfile`, `handle_errors`),
including when the PC itself answers 502, 503 or 504. The page reloads itself every 30 seconds. To change the live front, edit the
`caddyfile` instance metadata, run `caddy validate` on the VM, copy it to `/etc/caddy/Caddyfile` and `systemctl reload caddy`
(graceful, no dropped requests).
