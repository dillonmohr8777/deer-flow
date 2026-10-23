# MomoBot prod on AWS EC2

The Lightsail kit (`../lightsail/`) running on one EC2 instance, because the AWS account may not create a
Lightsail plan larger than the smallest sizes. Same compose layers, Caddy (automatic TLS) and nightly S3 backup.
EC2 adds three things:

- **Secrets in memory only.** The instance role (`momobot-ec2`) may read `/momobot/prod/*` in SSM Parameter Store
  and write the backup bucket, nothing else. `secrets.sh` runs before every start and writes `/run/momobot/.env`
  (tmpfs, root 600). These environment credentials stay out of git and backups;
  the private gateway backup still contains its JWT signing secret and user data.
- **The gateway's extra mounts** (`compose.ec2.yaml`): skills, admission, lobby notes, brand kit, evals and the
  two browser guard modules, from `/opt/momobot/data` and `/opt/momobot/code`, plus the pinned placement
  extension (see Operator extensions).
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
/opt/momobot/extensions/placement   pinned git worktree for the placement extension (runtime code, not backed up)
```

### Operator extensions

The placement extension (`examples/vhin-placement`) is not in the image yet, so compose bind-mounts it
read-only from a detached worktree pinned to the image's SHA. Pinning keeps image rollback and
extension code independent of the `/opt/momobot/src` checkout. Update it on purpose, under
`/run/momobot-release.lock`:

```sh
sudo git -C /opt/momobot/src worktree add --detach /opt/momobot/extensions/placement <image-sha>
# later: sudo git -C /opt/momobot/extensions/placement checkout --detach <new-sha>
```

It stays inert until `/opt/momobot/config.yaml` has a `plugins:` entry with `use: vhin_placement:install`,
`required: false`, no `package:`, and every config key in that example's README. Put `data_dir` inside the
gateway volume (`/app/backend/.deer-flow/extensions/<name>`) so the nightly gateway snapshot backs it up
and `gateway-data.tgz` restores it. Readback after a restart: `docker logs momobot-prod-gateway | grep
extension`, then an authenticated `GET /api/vhin/state`. Its SQLite file uses rollback-journal mode: if a
gateway crash leaves a hot journal, the nightly backup fails on that file (health.sh flags the stale
stamp). One authenticated desk request rolls the journal back; then rerun the backup.

## Operate

```bash
sudo systemctl restart momobot          # fetch secrets, then lightsail/up.sh
sudo systemctl start momobot-backup     # backup now; prints the s3:// object
sudo MOMOBOT_ENV_FILE=/run/momobot/.env MOMOBOT_EXTRA_COMPOSE=/opt/momobot/src/deploy/momentum/ec2/compose.ec2.yaml \
  /opt/momobot/src/deploy/momentum/lightsail/up.sh compose logs -f gateway
```

Release, from an operator checkout: `MOMOBOT_SSH=<user@host> MOMOBOT_SSH_KEY=<key> deploy/momentum/ec2/release.sh <sha>`.
Under `/run/momobot-release.lock` it checks out the merged commit, builds `deer-flow-{gateway,frontend}:main-<sha8>`
unless the box has them, swaps both tags in `settings.env`, runs `systemctl restart momobot`, waits for
`/health/ready` and smoke-checks the running images plus the public API and UI. A failure after the swap
restores the previous source and tags by itself. On success it tags `momobot-prod-YYYYMMDD-<sha8>` and opens a
PR adding the release to `docs/MOMOBOT_CHANGELOG.md`. `release.sh rollback` restores the previous release.
Every attempt is a line in `/var/log/momobot/releases.jsonl`. Offline check: `backend/tests/test_ec2_release_script.py`.

The existing `momobot-health.timer` checks gateway readiness, public API and UI,
backup freshness, and at least 10 GiB free on the deployment filesystem. Its JSON
receipt includes `publicUi` and `diskAvailableMiB`; unknown capacity fails the check.
Before a release, recover headroom under `/run/momobot-release.lock` using unused
Docker build cache or verified unused builder images. Preserve running containers,
volumes, production and rollback images. Compare filesystem bytes before and after;
Docker's advertised reclaimable size is not recovered space. Larger builds still
need a budget for their own peak temporary storage.

The Momentum templates use a 300-super-step default with the existing 1000-step ceiling.
Middleware nodes consume super-steps too: the former 100-step default interrupted an
eight-model-call AM plugin check. For an existing EC2 config, promote only this top-level
`recursion_limit` value; preserve model, memory, credential and workspace settings. Verify
the effective default and ceiling and a complete AM tool run without a request override.

## Optional 1Password Browserbase credentials (prepared, not deployed)

The existing `secrets.sh` SSM read passes its decrypted JSON directly to
`render_secrets.py`. Without `/momobot/prod/OP_SERVICE_ACCOUNT_TOKEN`, the loader
uses SSM values and needs only host Python 3, with no SDK import or vault call.
When that parameter exists, a host-only SDK client resolves exactly these fields:

- `BROWSERBASE_API_KEY`: `op://ezfukkmm4vt7wqw6vp7l7eli3m/bjil477nt5c433kto6ys3qejw4/credential`
- `BROWSERBASE_PROJECT_ID`: `op://ezfukkmm4vt7wqw6vp7l7eli3m/bjil477nt5c433kto6ys3qejw4/project_id`

The resolved values replace the SSM Browserbase pair. All other app secrets and
non-secret settings retain their existing order and behavior. The service-account
token is never emitted, and `settings.env` must contain neither that token nor
Browserbase overrides when 1Password is enabled. Empty token/resolved values,
invalid env names, quotes, newlines, carriage returns and NULs fail closed.
Legacy empty app-secret values remain permitted. Validation and resolution finish
before any env output; failure leaves the prior `/run/momobot/.env` intact and
prevents systemd startup. Diagnostics contain no submitted value or traceback.

Deployment owner prerequisites and sequence, through the existing release lock:

1. Promote the reviewed commit containing both loader files. Keep the existing
   SSM Browserbase pair for rollback. Do not enable the token before host SDK setup.
2. Install a root-owned, host-only Python 3.12 venv outside the app/container:

   ```sh
   sudo python3.12 -m venv /opt/momobot/onepassword-sdk
   sudo /opt/momobot/onepassword-sdk/bin/pip install 'onepassword-sdk==0.4.1'
   ```

3. Add `/etc/systemd/system/momobot.service.d/onepassword.conf` with only:

   ```ini
   [Service]
   Environment=MOMOBOT_SECRETS_PYTHON=/opt/momobot/onepassword-sdk/bin/python
   ```

   Use the existing protected provisioning process to store the scoped service
   account token as SSM SecureString `/momobot/prod/OP_SERVICE_ACCOUNT_TOKEN`.
   The instance role already reads that path. No token belongs in this drop-in,
   `settings.env`, command arguments, app env, logs, model prompts or Git.
4. Run `sudo systemctl daemon-reload`, then restart `momobot` through the existing
   unit. Verify root `0600` env permissions and token-key absence with a boolean
   check that never prints env contents. Verify authenticated Browserbase session
   creation and release with a public synthetic target, then MomoBot readiness.
   A successful env write alone does not prove Browserbase runtime acceptance.

Rollback: remove only the service-account parameter via the protected provisioning
process, then restart the existing unit. The retained SSM Browserbase pair is used
again; the host interpreter can remain configured without vault calls. A source
rollback must preserve token exclusion before startup, so never run the previous
unfiltered loader while the SSM service-account token still exists.

Offline checks (stdlib only, fake AWS/SDK, no credentials or provider calls):

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s deploy/momentum/ec2/tests -v
bash -n deploy/momentum/ec2/secrets.sh
```

## 1Password logins for the isolated Browserbase MCP (Oct 21, 2026)

MomoBot's `browserbase` MCP (`operator-tools/browserbase-mcp` in the gateway data volume; source:
`browser-agents/mcp`) exposes `browser_login {item}`. The model passes only a 1Password item name.
The MCP sends `{session, item}` to `login_broker.py` over the Unix socket
`/var/lib/docker/volumes/momobot-prod_gateway-data/_data/run/login.sock` (container path
`/app/backend/.deer-flow/run/login.sock`). The broker runs on the host, outside every container, with the
SSM service-account token. It resolves the item, attaches to that exact Browserbase session and fills the
form. It replies with a status and page host/path only. Values never reach the gateway, the model or the journal.

Guards: Login items tagged `momobot` only; session RUNNING in our project with `userMetadata.owner`
`momobot-isolated-mcp`; https page whose host equals or is under one of the item's websites. An OTP field
gets the item's `one-time password` code only when the page reads like a 2FA prompt. The host is re-checked
before every fill, a password left in a failed form is cleared, titles used twice are refused, and the item
index is cached for 60 s so retries cannot exhaust the service-account rate limit. MCP sessions use `keepAlive: true`, so the broker's CDP attach
does not end them. `browser_close` and the 300 s provider timeout still release them.

Add a login: put a Login item (website set; one-time password field for TOTP) in a vault the service
account can read and tag it `momobot`. Client logins belong in a shared `Clients` vault. Service-account
vault access is fixed at creation, so `Clients` needs its own read-only service account. Store its token as
SSM SecureString `/momobot/prod/OP_CLIENTS_TOKEN`. The broker reads it at start when present (restart the
broker after adding it). `render_secrets.py` drops it, like `OP_SERVICE_ACCOUNT_TOKEN`, so it never reaches the app env.

Install or update (under `/run/momobot-release.lock`):

```sh
# pinned git worktree of the merged commit (no hand-copied files); move it to update
sudo git -C /opt/momobot/src fetch origin main
sudo git -C /opt/momobot/src worktree add --detach /opt/momobot/login-broker <merged-sha>
sudo install -d -m 700 /var/lib/docker/volumes/momobot-prod_gateway-data/_data/run
sudo /opt/momobot/onepassword-sdk/bin/pip install 'playwright==1.58.0'          # client only; no browser download
sudo install -m 644 systemd/momobot-login-broker.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now momobot-login-broker
journalctl -u momobot-login-broker -n 5   # {"broker": "ready", "accounts": N, "items": N}; one status line per login
```

Copy the reviewed MCP files (`server.mjs cloud.mjs policy.mjs login.mjs`) into the volume directory.
New MCP processes pick them up, and no gateway restart is needed. Rollback: `systemctl disable --now
momobot-login-broker`. `browser_login` then answers `login_broker_unavailable`, and the other 15 tools are
unchanged.

## Nightly recovery contents

The existing backup timer includes the consistent gateway SQLite snapshot, config and MCP settings,
a Redis-native RDB snapshot verified by `redis-check-rdb`, and the seven EC2 data and guard bind mounts
listed above (the extension worktree is code from git and is recreated, not backed up).
`ec2-recovery.json` carries only the known non-secret image/domain/frontend-owner settings needed to
recreate `settings.env` and `frontend.env`. Environment files remain excluded; reload credentials
from SSM. The gateway snapshot contains private user data and its JWT signing secret, so keep the
S3 bucket private and encrypted.

For a replacement host, install the merged source and EC2 kit, recreate the pinned extension worktree
(compose refuses to start without it), verify every `MANIFEST.sha256` entry,
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

## Private read-only Brain snapshot

`brain_readonly_adapter.py` preserves the existing fixed-destination HTTP adapter and adds
an offline mode selected by `BRAIN_SNAPSHOT_DIR`. The existing collector remains the only
Brain writer.

For snapshot mode, the deployment owner keeps the unchanged trusted `brain.py` renderer
in a private directory mounted read-only on EC2. Run the adapter with the existing gateway
Python interpreter:

```sh
BRAIN_SNAPSHOT_DIR=/opt/momobot/brain-snapshot python3 brain_readonly_adapter.py
```

Keep all snapshot files outside Git and model prompts. Only `brain_now`, `brain_client`,
`brain_open_items`, and `brain_systems` are exposed; calls go directly to pure renderer
functions. The adapter never invokes Brain's auto-refreshing `load`, collector, capture,
search, or HTTP service in snapshot mode. No bearer token or new network endpoint is needed.
Every tool result and listed tool includes the saved `generated_at` as `sourceObservedAt`
and a `generation` identifier. `generated_at` records the collector's build observation,
not the freshness of every underlying record. Transfer/publication time does not change it.
Old snapshots remain explicitly saved observations; no freshness TTL or live communication
sweep is implied. Refresh cadence and source-age checks remain the owner's responsibility.

The deployment owner stages the private renderer/cache and the adapter, keeps the `brain`
MCP entry pointed at `/run/momo-security/brain_readonly_adapter.py`, and verifies useful MCP
output and the denials before enabling it. Do not
add a collector, timer, Mac bridge or competing writer. Cache transfer, authentication,
production integration and client-scoped access remain unverified by the offline test.

`compose.ec2.yaml` mounts both read-only into the gateway container only, with
`create_host_path: false` so a release fails instead of creating empty paths:
`/opt/momobot/brain-snapshot` (0700, root, files 0600) and the adapter at
`/run/momo-security/brain_readonly_adapter.py` (staged from this directory to
`/opt/momobot/code/`, covered by `backup_extra.py`). The snapshot is not backed up; it is
regenerated from the Mac Brain. The `brain` MCP entry carries `private_scope` (Dillon's actor
plus exact private organization) and `BRAIN_SNAPSHOT_DIR=/opt/momobot/brain-snapshot`.

The existing bound root directory must retain its inode. Do not `mv` a replacement directory
over `/opt/momobot/brain-snapshot`, or rsync a new pair over the selected generation.
`brain.py` stays in that root-only directory; only the deployment owner stages trusted code.
The adapter pins its bytes at startup and fails reads if those bytes change. A planned
renderer upgrade requires owner validation and an adapter restart.

For each manual refresh, transfer the existing Mac-built `brain.json` and `NOW.md` to a
separate private staging directory. With the reviewed adapter and publisher side by side
on the host, the owner invokes the publisher using the renderer hash already verified in
the release receipt:

```sh
python3 publish_brain_snapshot.py \
  --source-dir /opt/momobot/private-brain-stage \
  --snapshot-dir /opt/momobot/brain-snapshot \
  --renderer-sha256 "$VERIFIED_BRAIN_RENDERER_SHA256"
```

This explicit host command has no MCP refresh operation, timer, upstream request or collector
side effect. It executes only the hash-verified root renderer, never source-directory code.
It requires exact `render_now(brain.json) == NOW.md` agreement, required JSON shapes and an
aware observation timestamp. Pair mtimes are not coherence evidence. Files are bounded to
1 MiB each; metadata is bounded to 4 KiB. Duplicate JSON keys, non-finite numbers, linked or
special files, symlinked directories and non-hex generation paths are rejected.

The publisher writes private files (0600) in a new generation directory (0700) inside
`generations/`. Its manifest binds both payload hashes, the trusted renderer hash and the
original observation timestamp into the generation ID. It flushes/fsyncs payloads and
directories, then atomically replaces only `current.json` and fsyncs the bound root. Existing
generation contents are never rewritten. An identical selected generation is a validated
no-op; observations older than the currently published one are rejected. An exclusive
`.publish.lock` rejects concurrent publishers, and a changed pointer before commit aborts
publication. A crash can leave a lock or an unselected staging/generation directory; the
owner checks that no publisher is active before removing a leftover lock. Cleanup is manual.

Validation, staging and fsync failures before pointer replacement preserve the previous
pointer. A failure after replacement can mean publication committed but its crash durability
is unconfirmed; inspect `current.json` and validate destination reads before retrying. CLI
failures emit only `Brain snapshot publication failed.` Success prints generation,
`sourceObservedAt` and whether the selection changed, with no snapshot body.

On every permitted tool read/list, an already-running requester checks the bounded pointer.
It validates the entire selected generation, then rechecks the pointer before swapping its
complete in-memory state when the selection changes. An unchanged pointer also requires
full validation before serving its cached state, detecting selected-file deletion or damage
after an earlier successful read. Generations are immutable by publisher convention;
root privileges can still alter them. Malformed, missing or mismatched selected data returns the existing generic error,
without silently serving the cached prior generation. The read-only bind exposes in-place
pointer changes without a gateway recreation. Destination acceptance still requires the owner
to verify all four tools and listed tool metadata from the same running requester.

Legacy migration: before any pointer is present, startup accepts a bounded, schema-validated
root `brain.json`/`NOW.md` pair only if the trusted renderer reproduces it exactly. It labels
that frozen startup state `generation=legacy`. Later root-pair writes do not refresh that
cache; the first successful pointer publication switches the same process to generation mode.
Once a process has observed a pointer, removing it fails closed. Do not remove the pointer
after migration: a restart without it explicitly re-enters legacy startup validation. Keep
the root legacy pair unchanged while migrating; a mixed pair now fails startup validation.
Do not use pointer deletion as rollback.

To roll back data, the owner atomically selects a retained, validated prior generation by
writing a valid `current.json` pointer with `schemaVersion: 1` and its 64-character hex
`generation` ID, using the same exclusive `.publish.lock` ownership, flush/fsync and
atomic-replace procedure. All pointer writers must honor that lock. The reader permits
that explicit selection and reports the older saved observation. The publisher intentionally
does not accept an observation regression. No automatic pruning or rollback is performed.

To disable access, set `enabled: false` on the `brain` entry (no tool is offered). To withdraw the data
as well, empty `/opt/momobot/brain-snapshot`; the gateway is root, so a mounted file is
readable by any gateway process.

Offline contract check (synthetic fixture only):

```sh
cd backend
python -m pytest tests/test_ec2_brain_snapshot.py -q --noconftest
```

The publisher targets POSIX hosts with directory fsync support. Windows tests substitute
directory fsync only; run the same synthetic suite on POSIX before owner runtime acceptance.

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

In the existing private config, append only the ten `composio-marketing_<tool-name>`
targets from this policy to `authorization.provider.config.roles.user.tools.allow`.
Preserve every other permission and role; do not add a wildcard or an execution helper.
Verify all ten targets are allowed and private Composio tools remain denied.

## Momo Daily staff portraits

Keep the seven staff portraits outside Git in `/opt/momobot/data/brand/daily-people`, named by the slugs in `frontend/src/components/momentum/daily/staff-box.tsx`, as WebP files. The EC2 layer mounts that directory read-only into the frontend public assets. The existing encrypted brand backup includes it. Before release, compare each staged file SHA-256 with its source receipt; after release, fetch all seven rendered portraits and reject placeholder fallbacks. Never add these private images to the public repository or bake them into an untracked local build.
