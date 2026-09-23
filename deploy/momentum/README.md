# Momentum deployment

The live Momentum stack, reproducible from this repo. Replaces the scripts in
`Codex/2026-09-20/https-x-com-korzhov-dm-status/`. As of 2026-09-22 those are
broken: the deploy worktree they compose from and the image their secrets
loader runs were both removed.

| File | Role |
|---|---|
| `workspace.config.yaml` | Live gateway config, byte-identical to the mounted one on 2026-09-22. Real keys are `$OPENROUTER_API_KEY` / `$AI_GATEWAY_API_KEY` from `.env`; the Ollama `api_key: ollama` values are placeholders. |
| `compose.momentum.yaml` | Overlay on `docker/docker-compose.yaml` + `docker-compose.dood.yaml`: pinned image tags, tailnet listener. |
| `restart.ps1` | Start or restart the stack. `-WhatIfOnly` renders config and changes nothing. |
| `load-secrets.ps1` | Loads service credentials stored in the gateway volume. Never prints them. |
| `backup_volume.py` | Consistent snapshot of the gateway volume into an empty volume, safe while live. |
| `compose.rehearsal.yaml` | Container names for a side-by-side restore rehearsal. |

Needs, outside git: `.env`, `frontend/.env`, `extensions_config.json`, and the
`<project>_gateway-data` volume (holds the DB, `.jwt_secret`, service credentials).

## Back up

```powershell
docker volume create deer-flow-backup-<date>
docker run --rm --network none `
  --mount type=volume,source=deer-flow_gateway-data,target=/source `
  --mount type=volume,source=deer-flow-backup-<date>,target=/backup `
  --mount type=bind,source=<repo>/deploy/momentum/backup_volume.py,target=/tmp/backup.py,readonly `
  --entrypoint python <gateway image> /tmp/backup.py
```

## Restore rehearsal (verified 2026-09-22)

Snapshot into `deer-flow-rehearsal_gateway-data`, then:

```powershell
./deploy/momentum/restart.ps1 -ProjectName deer-flow-rehearsal -Port 2027 -TailnetHost 127.0.0.1 `
  -ExtraComposeFile deploy/momentum/compose.rehearsal.yaml
```

Result: 4/4 healthy, HTTP 200. Matched live on alembic head `0030`, 94
project-document rows (hash), 9 users, 156 user files (hash), JWT secret
(hash), and 164 OpenAPI paths. Live containers were not touched.

Before starting a rehearsal, confirm the copy cannot act: no rows in
`channel_connections`, no pending runs or batches, `scheduler.enabled: false`.

## Encrypted off-machine backup (nightly)

`offsite_backup.py` snapshots `deer-flow_gateway-data` with `backup_volume.py`, then:

- tars the snapshot and encrypts it with AES-256-GCM;
- writes `gateway-data-<stamp>.tgz.enc` plus a receipt to `OneDrive\MomoBot-Backups`, which syncs off the machine;
- reads the file back and decrypts it to confirm the hash, then keeps the newest 14.

The key is 32 random bytes at `C:\Users\dillo\Documents\Qwen\.secrets\momobot-backup.key`. It's outside every synced folder and never printed. Keep a second copy in a password manager: without it, the backups can't be restored.

**Restore:** `python offsite_backup.py --restore <file.enc>` decrypts to a local temp `.tgz`, never into the synced folder. Then extract it into an empty volume and rehearse on `:2027` before touching live.

**Schedule:** a Windows scheduled task named "MomoBot offsite backup" runs daily at 03:15 using `pythonw`, so no window opens. It needs Docker Desktop running.
