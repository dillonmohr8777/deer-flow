# MomoBot prod on AWS EC2

The Lightsail kit (`../lightsail/`) running on one EC2 instance, because the AWS account may not create a
Lightsail plan larger than the smallest sizes. Same compose layers, Caddy (automatic TLS) and nightly S3 backup.
EC2 adds three things:

- **Secrets in memory only.** The instance role (`momobot-ec2`) may read `/momobot/prod/*` in SSM Parameter Store
  and write the backup bucket, nothing else. `secrets.sh` runs before every start and writes `/run/momobot/.env`
  (tmpfs, root 600). Nothing secret is on disk, in git or in the backups.
- **The gateway's extra mounts** (`compose.ec2.yaml`): skills, admission, lobby notes, brand kit, evals and the
  two browser guard modules, from `/opt/momobot/data` and `/opt/momobot/code`.
- **systemd drop-ins** (`systemd/`) that point the kit's units at the tmpfs env file and the EC2 layer.

## Layout on the box

```
/opt/momobot/src              git checkout (this repo)
/opt/momobot/config.yaml      gateway config (cloud copy: no Mac-only models, tools or MCP servers)
/opt/momobot/extensions_config.json
/opt/momobot/frontend.env     MOMO_DAILY_CLOUD_OWNER_USER_ID only
/opt/momobot/settings.env     non-secret: MOMOBOT_DOMAIN, MOMOBOT_ACME_EMAIL, image tags, GATEWAY_ENABLE_DOCS
/opt/momobot/data/{skills,admission,lobby-notes,brand,evals}
/opt/momobot/code/{momo_guard.py,momo_protocol.py}
```

## Operate

```bash
sudo systemctl restart momobot          # fetch secrets, then lightsail/up.sh
sudo systemctl start momobot-backup     # backup now; prints the s3:// object
sudo MOMOBOT_ENV_FILE=/run/momobot/.env MOMOBOT_EXTRA_COMPOSE=/opt/momobot/src/deploy/momentum/ec2/compose.ec2.yaml \
  /opt/momobot/src/deploy/momentum/lightsail/up.sh compose logs -f gateway
```

Release: build `deer-flow-{gateway,frontend}:main-<sha8>` on the box from the merged commit, set both tags in
`settings.env`, then `systemctl restart momobot`. Rollback: put the previous tags back and restart.

## Not on the box (Mac-only, off in the cloud config)

Brain MCP (Mac bridge :8787), client_browser MCP (:8788), the Jevbox evidence tool (:4310) and the local
Ollama/oMLX models. Reaching them needs a tunnel back to the Mac. That is a follow-up, and MomoBot runs without them.


## Optional read-only Brain snapshot (prepared, not enabled)

`brain_readonly_adapter.py` preserves the existing fixed-destination HTTP adapter and adds
an offline mode selected by `BRAIN_SNAPSHOT_DIR`. It does not enable an MCP server or alter
production configuration. The existing collector remains the only Brain writer.

For snapshot mode, the deployment owner installs one coherent private directory containing
`brain.json`, `NOW.md`, and the unchanged trusted `brain.py` renderer. Mount it read-only on
EC2 and run the adapter with the existing gateway Python interpreter:

```sh
BRAIN_SNAPSHOT_DIR=/opt/momobot/brain-snapshot python3 brain_readonly_adapter.py
```

Keep those three files outside Git and model prompts. Only `brain_now`, `brain_client`,
`brain_open_items`, and `brain_systems` are exposed; calls go directly to pure renderer
functions. The adapter never invokes Brain's auto-refreshing `load`, collector, capture,
search, or HTTP service in snapshot mode. No bearer token or new network endpoint is needed.
Every result includes the saved `generated_at` as `sourceObservedAt`, even if the files are
old. These are saved observations, not live health or a fresh communication sweep.

The deployment owner must independently review the change, stage the private renderer/cache
and adapter, add a read-only mount, replace the missing `/run/momo-security` adapter path in
the existing disabled MCP entry, then verify useful MCP output before enabling it. Do not
add a collector, timer, Mac bridge or competing writer. Cache transfer, authentication,
production integration and client-scoped access remain unverified by the offline test.

Offline contract check (synthetic fixture only):

```sh
cd backend
python -m pytest tests/test_ec2_brain_snapshot.py -q --noconftest
```
