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
# set both image tags in /opt/momobot/.env, create /opt/momobot/MAINTENANCE, run pc-up.sh, then remove MAINTENANCE
```

`../ec2/release.sh` targets the old EC2 box over SSH and does not apply here.

## Restore

Decrypt with `openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass file:KEY -in momobot-<stamp>.tgz.enc | tar xzf -`,
check `MANIFEST.sha256`, extract `gateway-data.tgz` into an empty `momobot-prod_gateway-data` volume, copy
`redis.rdb` into the redis volume as `dump.rdb`, then run `pc-up.sh` (it restores the private modes).
