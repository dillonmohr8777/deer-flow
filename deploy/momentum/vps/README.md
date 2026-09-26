# Always-on MomoBot on a Linux VPS

The live Momentum instance (today `:2026` on Dillon's Windows PC, tailnet only)
moves to an always-on Linux server at `https://momobot.needmomentum.com`, so
the team can sign in with Google from anywhere. `:2028` (Dillon's owner-only
workspace, with host shell and personal Gmail/Drive) does **not** move here
and is never merged into this instance.

| File | Role |
|---|---|
| `compose.public.yaml` | Overlay: Caddy on 80/443 with automatic TLS for `$MOMOBOT_DOMAIN`, proxying to nginx. nginx's own port stays on loopback. |
| `Caddyfile` | The public site: HTTPS, HSTS, no response buffering (streaming works). |
| `restart.sh` | Start or restart: base compose + dood + `compose.momentum.yaml` + Postgres + public overlay. `--what-if` prints the merged config and changes nothing. Never builds. |
| `health.sh` | Docker, loopback UI, `/health/ready`, the public URL, and a backup receipt under 26 h. One JSON line per run to `/var/log/momobot/health.jsonl`; exit 1 means look. |
| `backup.sh` | Nightly encrypted backup via `../offsite_backup.py`, with the snapshot image taken from `MOMENTUM_GATEWAY_IMAGE` in `.env` so it always exists on this server; also `pg_dump`s the live Postgres container (detected from `POSTGRES_PASSWORD` in `.env`) into its own encrypted file, since users/threads/checkpoints/run_events live there, not in the gateway volume. |
| `dotenv-get.sh` | Reads one non-secret value from `.env` without sourcing it. systemd never loads `.env`: its parser differs from compose's and would outrank `--env-file`. |
| `systemd/` | `momobot.service` (start at boot), `momobot-health.timer` (every 15 min), `momobot-backup.timer` (nightly). |

## Who does what

| Step | Who | Why |
|---|---|---|
| Power on `hermes-vps`, run `sudo tailscale up --ssh` | Dillon | Provider console access |
| Google OAuth client (consent screen in **Testing**, the invitees as test users; redirect `https://momobot.needmomentum.com/api/v1/auth/callback/google`) | Dillon | Credentials |
| DNS: `A momobot -> <VPS public IP>` at SiteGround | Dillon or Mac | Momentum's domain |
| Everything else below | Claude, over Tailscale SSH | |
| Data cutover from the PC (`:2026`) | Claude, **only on Dillon's go** | Moves client data |

## 1. Server basics (Ubuntu or Debian, once)

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 python3-cryptography curl git ufw
sudo usermod -aG docker "$USER"
# Log out and back in (or run `newgrp docker`) before step 4: group
# membership only applies to new sessions.
# Public: only 80/443. SSH stays reachable over Tailscale only.
sudo ufw default deny incoming && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw allow 443/udp
sudo ufw allow in on tailscale0 && sudo ufw --force enable
sudo mkdir -p /srv/momobot/{backups,secrets} /var/log/momobot && sudo chown -R "$USER" /srv/momobot /var/log/momobot
# <release> is the tag cut after this kit and the app changes it depends on
# are merged (see step 3). Never a draft branch, never plain `main`.
git clone --branch <release> https://github.com/dillonmohr8777/deer-flow.git /srv/momobot/deer-flow
```

## 2. Secrets and config (outside git)

`/srv/momobot/deer-flow/.env`, mode 600. Names only here; values never go in chat or git:

```
MOMOBOT_DOMAIN=momobot.needmomentum.com
MOMOBOT_ACME_EMAIL=<address for certificate notices>
MOMENTUM_GATEWAY_IMAGE=<the gateway tag you loaded or built in step 3>
MOMENTUM_FRONTEND_IMAGE=<the frontend tag>
POSTGRES_PASSWORD=<long random>
GOOGLE_OAUTH_CLIENT_ID=<from Google Cloud>
GOOGLE_OAUTH_CLIENT_SECRET=<from Google Cloud>
OPENROUTER_API_KEY=<same keys the PC stack uses>
AI_GATEWAY_API_KEY=<same>
```

Changes to `deploy/momentum/workspace.config.postgres.yaml` for this server
(make them on the server copy, review the diff, then commit the non-secret
parts):

```yaml
auth:
  local:
    allow_registration: false          # unchanged: people join by invite
  oidc:
    enabled: true
    frontend_base_url: https://momobot.needmomentum.com
    providers:
      google:
        display_name: Google           # the button reads "Continue with Google"
        issuer: https://accounts.google.com
        client_id: $GOOGLE_OAUTH_CLIENT_ID
        client_secret: $GOOGLE_OAUTH_CLIENT_SECRET
        redirect_uri: https://momobot.needmomentum.com/api/v1/auth/callback/google
        scopes: [openid, email, profile]
        token_endpoint_auth_method: client_secret_post
        auto_create_users: true
        auto_create_requires_invitation: true   # PR #42: only invited emails get accounts
        require_verified_email: true
        admin_emails: []
        pkce_enabled: true
        nonce_enabled: true

momentum_internal:                     # Team channels + AI Academy (PR #38)
  enabled: true
  organization_slugs: [<the Momentum workspace slug>]
```

Also set the team's default chat model to one allowed to see client data
(not Muse Spark).

Most of the team signs in with personal @gmail.com accounts, so
`allowed_email_domains` can't fence sign-ups. Two fences instead:
`auto_create_requires_invitation: true` (only emails holding a pending invite
get an account, PR #42), and the Google consent screen kept in **Testing**
with only the invited people as test users.

## 3. Images

`restart.sh` never builds. Put the images on the server one of two ways:

- **Load the verified tags** from a machine that has them:
  `docker save deer-flow-gateway:<tag> deer-flow-frontend:<tag> | ssh hermes-vps docker load`
  then set `MOMENTUM_GATEWAY_IMAGE` / `MOMENTUM_FRONTEND_IMAGE` in `.env`.
- **Build on the server** from a reviewed commit:
  `git checkout <commit> && docker compose -f docker/docker-compose.yaml build gateway frontend`,
  then tag and set the same two variables. The frontend build wants several GB of RAM.

The release that carries Team/Academy (PR #38) and Google invites (PR #42)
has to be merged and tagged first; don't point a live server at a draft branch.

## 4. Start, then make it permanent

```bash
cd /srv/momobot/deer-flow
deploy/momentum/vps/restart.sh --what-if > /tmp/merged.yaml   # review
deploy/momentum/vps/restart.sh
sudo cp deploy/momentum/vps/systemd/momobot*.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now momobot.service momobot-health.timer momobot-backup.timer
```

Verify: `https://momobot.needmomentum.com/login` shows **Continue with Google**;
`deploy/momentum/vps/health.sh` prints `"ok":true` after the first backup.

## 5. Off-machine backups

`momobot-backup.timer` writes encrypted archives and receipts to
`/srv/momobot/backups`. The key (`/srv/momobot/secrets/momobot-backup.key`) is
created on first run: copy it into the password manager **that day**, or the
backups can't be restored if the server dies. Off-machine copy: the Mac pulls
the encrypted files nightly over Tailscale (launchd job running
`rsync -a hermes-vps:/srv/momobot/backups/ ~/MomoBot-Backups/`); the files are
useless without the key, which never leaves the password manager and the server.

This server runs Postgres (`compose.postgres.yaml`), so **users, threads,
checkpoints and run_events live in the database, not in the
`deer-flow_gateway-data` volume**. `backup.sh` detects that from
`POSTGRES_PASSWORD` in `.env` and has `offsite_backup.py` `pg_dump` the live
container (no password needed: it runs inside the container over its own
trusted local socket) into a second encrypted file per run,
`postgres-<stamp>.dump.enc`, sitting next to `gateway-data-<stamp>.tgz.enc`
with the same restore-check and retention. A receipt whose `"postgres"` field
is `null` means this host has no Postgres container configured (not this VPS);
`"state": "FAIL"` there means the dump didn't verify, same as the volume tar.

**Restore a login after losing the server** (rehearse on a throwaway host
before ever pointing `MOMOBOT_DOMAIN` at it):

```bash
# 1. Decrypt both files with the key copied into the password manager in step above.
python3 deploy/momentum/offsite_backup.py --restore /path/to/gateway-data-<stamp>.tgz.enc
python3 deploy/momentum/offsite_backup.py --restore /path/to/postgres-<stamp>.dump.enc
# Each prints where it decrypted to and the exact follow-up command:
#   the gateway-data one -> load its .tgz into a fresh, empty
#     deer-flow_gateway-data volume (docker run ... tar xzf ...)
#   the postgres one -> docker cp the .dump into the new postgres container,
#     then pg_restore --clean --if-exists into it
# 2. Start the stack against the restored volume and freshly restored database:
deploy/momentum/vps/restart.sh
# 3. Verify: sign in with an existing account (no re-invite needed -- the
#    restored users table already has it) and confirm a recent thread matches.
```

A restore that skips the `pg_dump` half brings back the gateway volume (skill
files, sandbox state) with none of the actual accounts, threads or messages —
`docker exec deer-flow-postgres psql -U deerflow -d deerflow -c '\dt'` on a
volume-only restore shows no tables at all, since Postgres owns its own data
directory in `postgres-data`, separate from `deer-flow_gateway-data`.

## 6. Data cutover from the PC (only on Dillon's go)

1. Freeze writes on the PC stack (announce a short window).
2. On the PC: `python deploy/momentum/offsite_backup.py` (encrypted snapshot of `deer-flow_gateway-data`).
3. Copy the archive to the server over Tailscale; restore with `offsite_backup.py --restore FILE` into `deer-flow_gateway-data` before the first start.
4. If the PC runs SQLite and the server runs Postgres, follow `../POSTGRES-REHEARSAL.md` for the SQLite to Postgres step. Rehearse on a copy first.
5. Start the server, sign in, and check the Momentum workspace, a client workspace, and a recent thread against the PC.
6. Only then create the team's invites (Momentum workspace, Invite member) and send each person their link in the same Slack DM they already have.

Rollback: stop the server stack; the PC stack is untouched and can be unfrozen.
