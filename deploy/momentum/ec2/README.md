# MomoBot prod on AWS EC2

The Lightsail kit (`../lightsail/`) running on one EC2 instance, because the AWS account may not create a
Lightsail plan larger than the smallest sizes. Same compose layers, Caddy (automatic TLS) and nightly S3 backup.
EC2 adds three things:

- **Secrets in memory only.** The instance role (`momobot-ec2`) may read `/momobot/prod/*` in SSM Parameter Store
  and write the backup bucket, nothing else. `secrets.sh` runs before every start and writes `/run/momobot/.env`
  (tmpfs, root 600). These environment credentials stay out of git and backups;
  the private gateway backup still contains its JWT signing secret and user data.
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

The Momentum templates use a 300-super-step default with the existing 1000-step ceiling.
Middleware nodes consume super-steps too: the former 100-step default interrupted an
eight-model-call AM plugin check. For an existing EC2 config, promote only this top-level
`recursion_limit` value; preserve model, memory, credential and workspace settings. Verify
the effective default and ceiling and a complete AM tool run without a request override.

## Nightly recovery contents

The existing backup timer includes the consistent gateway SQLite snapshot, config and MCP settings,
a Redis-native RDB snapshot verified by `redis-check-rdb`, and the seven EC2 bind mounts listed above.
`ec2-recovery.json` carries only the known non-secret image/domain/frontend-owner settings needed to
recreate `settings.env` and `frontend.env`. Environment files remain excluded; reload credentials
from SSM. The gateway snapshot contains private user data and its JWT signing secret, so keep the
S3 bucket private and encrypted.

For a replacement host, install the merged source and EC2 kit, verify every `MANIFEST.sha256` entry,
restore `gateway-data.tgz` into an empty gateway volume, and restore `ec2-mounts.tgz` under
`/opt/momobot`. Recreate the two non-secret env files from `ec2-recovery.json`. With Redis stopped
and an empty Redis volume, install `redis.rdb` as `dump.rdb` with the image's Redis ownership;
start Redis once without AOF so it loads the snapshot, then enable AOF before starting the stack.
Never overwrite a populated live volume. Snapshot checks are per service, not one atomic cross-service
transaction. A failed Redis or required EC2 mount snapshot fails the backup before its success stamp.

## Backup retention

Only `nightly/` expires: current nightly backups after 30 days and their old versions after 7 days.
The `mac-final-20261020/` archive contains originals removed from the Mac and must remain outside
automatic expiration. A bucket-wide empty prefix would delete those originals too.

Apply the checked-in policy from the repository root with the operator AWS profile, after reviewing
the current bucket policy for other rules that must be preserved:

```bash
aws s3api get-bucket-lifecycle-configuration --profile sunlit-servers \
  --bucket momobot-prod-backups-009688440435
aws s3api put-bucket-lifecycle-configuration --profile sunlit-servers \
  --bucket momobot-prod-backups-009688440435 \
  --lifecycle-configuration file://deploy/momentum/ec2/backup-lifecycle.json
aws s3api get-bucket-lifecycle-configuration --profile sunlit-servers \
  --bucket momobot-prod-backups-009688440435 --query Rules
```

## Not on the box (Mac-only, off in the cloud config)

Brain MCP (Mac bridge :8787), client_browser MCP (:8788), the Jevbox evidence tool (:4310) and the local
Ollama/oMLX models. Reaching them needs a tunnel back to the Mac. That is a follow-up, and MomoBot runs without them.


## Minimal memory profile image (prepared, not deployed)

`Dockerfile.memory-profile` copies only the two memory files reviewed in PR198 onto an
operator-verified immutable alias of the existing live gateway image. It runs no build
commands, installs no dependencies and changes no entrypoint, config, model default,
frontend or Brain integration. Supply a context containing only these two files exported
from commit `02c279db601a42ce731e5b3a8dd88e055aa6dcfc`, then build on EC2 with
`docker build --pull=false --network=none --build-arg BASE_IMAGE=<verified-local-alias> -f Dockerfile.memory-profile -t <new-candidate-tag> <context>`.
Verify the base image ID and candidate file hashes before changing a runtime tag. Keep the
previous gateway tag and settings snapshot for rollback through the existing systemd unit.
A named-profile probe alone does not establish production scope. Production acceptance needs
the deployed file hashes, readiness, authenticated output and a public-synthetic model receipt.

## Production memory model

Keep `memory.model_name: claude-haiku-5-5` in the cloud config. A null profile inherits the first
chat model, which is Opus for the administrator; account-manager chat permissions do not limit
this separate background extraction model. This pin applies to extraction for every role and
does not change the chat default, storage paths, user/agent scope or existing memories.

Before applying it, verify the configured Haiku profile exists, `memory.manager_class` is
`deermem`, `memory.backend_config.model.model` is empty and `memory.backend_config` has no
`host_llm` override. Preserve a private copy of the complete config and change only
`memory.model_name`, using the existing single-writer release lock. Restart `momobot` through
the existing unit so the cached memory manager rebuilds its model; `/api/memory/reload` reloads
stored data only. Read back the effective profile and readiness without printing credentials
or memory content. Rollback restores the saved config and restarts the same unit.

The offline profile-selection and workspace-scope checks are:

```sh
cd backend
python -m pytest tests/test_model_factory.py -k memory -q --noconftest
python -m pytest tests/test_org_isolation_g_memory.py -q
```

Do not trigger a Claude extraction probe during the 01:30–08:30 ET quiet window. A config
readback proves profile selection, not a completed provider extraction.

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

## Account-manager public research

`composio-marketing.policy.json` restricts the shared public-research session to ten
named public-query tools. It disables connection management, remote workbench,
proxy execution, search/meta execution and multi-execution; the provider-returned
configuration and tool list must match this policy before installation. Existing
private Gmail, Slack, Drive, analytics and advertising connections are excluded.

Create this session once in the existing Composio project, using the existing
protected credential. Save only its ordinary session ID in the release receipt.
Store the credential in SSM as `/momobot/prod/COMPOSIO_USER_API_KEY`, then bind the
returned official HTTPS MCP endpoint to an HTTP server named `composio-marketing`
in the existing private `extensions_config.json`. Pass `x-user-api-key` as the
`$COMPOSIO_USER_API_KEY` environment reference, plus the existing project/org scope
headers. Never commit or display the credential, returned URL or full MCP config.

Promote the reviewed policy through the existing EC2 release lock and systemd unit;
retain the prior extension/config files and image tags for rollback. Verify the
provider rejects an excluded private-app call, an ordinary AM can execute a public
read, and AM config access remains 403. Health stays unknown until those reads pass.
Public queries only; per-person/private client connections require their own scope.
