# Public MomoBot on the Mac mini (Tailscale Funnel)

The Momentum instance (today `:2026` on the Windows PC, tailnet only) runs on
the always-on Mac mini and is published with Tailscale Funnel at
`https://dillons-mac-mini.tailade026.ts.net`. Funnel terminates TLS inside
tailscaled; nginx listens on `127.0.0.1:2026` only, so nothing is reachable on
the LAN or the tailnet except through Funnel. `:2028` (owner-only) never moves
here.

| File | Role |
|---|---|
| `compose.funnel.yaml` | Overlay on `docker/docker-compose.yaml` + `docker-compose.dood.yaml`: fixed compose subnet, nginx at a fixed address with the realip include, `AUTH_TRUSTED_PROXIES` for the Gateway, image pins, `restart: unless-stopped`. |
| `nginx-realip.conf` | Trust `X-Forwarded-For` only from the compose network gateway, where tailscaled's connections arrive (f23). |
| `restart.sh` | Start or restart; waits for OrbStack; refuses a `.env` that is not mode 600; `--what-if` prints the merged config. Never builds. |
| `backup.sh` | Nightly encrypted backup via `../offsite_backup.py` into `~/momobot-prod/backups`, key in `~/momobot-prod/secrets` (0600). |
| `install-launchd.sh`, `launchd/` | Start at login, health every 15 min (`../vps/health.sh`), backup at 03:15. |

## Layout outside git (`~/momobot-prod`, mode 700)

```
.env                      600: OPENROUTER_API_KEY, BETTER_AUTH_SECRET, DEER_FLOW_INTERNAL_AUTH_TOKEN,
                          MOMENTUM_GATEWAY_IMAGE, MOMENTUM_FRONTEND_IMAGE, MOMOBOT_DOMAIN
frontend.env              may be empty
config.yaml               gateway config (see below)
extensions_config.json
src/                      clean clone at the deployed lane commit; src/.env and
                          src/frontend/.env are symlinks to the two files above
backups/ secrets/ logs/
```

Config differences from `../workspace.config.yaml` (the PC's live config):
GPT runs only as `openai/gpt-6-luna` with `reasoning_effort: max` (the legacy
`openrouter-luna`/`openrouter-terra` names are re-pinned to it), the
unconstrained `openrouter/auto-beta` router is pinned to a non-GPT model,
Vercel AI Gateway entries go through OpenRouter, and Ollama entries are
limited to models this Mac actually has.

## Docker engine

The scripts pin `DOCKER_HOST` to OrbStack (the CLI's default context on this
Mac is Docker Desktop). If `~/momobot-prod/docker-config` exists they use it:
a config with `"credsStore": "none"` and a no-op `docker-credential-none` in
`~/momobot-prod/bin`, so anonymous pulls never wait on a macOS keychain prompt
(the stock osxkeychain helper hangs there when nobody answers the dialog).

## Images

Build from the deployed commit, tag with the short SHA, then set both tags in `.env`:

```bash
cd ~/momobot-prod/src
docker compose -f docker/docker-compose.yaml build gateway frontend
docker tag deer-flow-gateway:latest  deer-flow-gateway:mac-<sha>
docker tag deer-flow-frontend:latest deer-flow-frontend:mac-<sha>
```

## Start and publish

```bash
~/momobot-prod/src/deploy/momentum/mac/restart.sh
~/momobot-prod/src/deploy/momentum/mac/install-launchd.sh
tailscale funnel --bg 2026        # https://<node>.<tailnet>.ts.net -> http://127.0.0.1:2026
```

If Funnel is not enabled for the tailnet, the CLI prints an admin-console URL
that the tailnet owner must open once.

Reboot survival needs the Mac to log in automatically (OrbStack and the
Tailscale app are login items); containers restart with OrbStack.

## Google sign-in

Redirect URI: `https://dillons-mac-mini.tailade026.ts.net/api/v1/auth/callback/google`
(JavaScript origin `https://dillons-mac-mini.tailade026.ts.net`). Enable the
`auth.oidc` block from `../vps/README.md` with that origin as
`frontend_base_url`, `auto_create_requires_invitation: true`, and the consent
screen in Testing.
