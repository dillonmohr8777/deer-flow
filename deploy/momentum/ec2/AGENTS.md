# EC2 deployment

The existing health timer runs lightsail/health.sh. It must check the public UI
as well as gateway readiness and fail on unknown disk space or less than 10 GiB
available on the deployment filesystem. Reuse this timer; never add a second watcher.

`secrets.sh` optionally resolves two fixed Browserbase references through the
host-only 1Password SDK when SSM contains `OP_SERVICE_ACCOUNT_TOKEN`. Never
render that token into the gateway env or expose a general secret-resolution
tool. Resolution and validation must finish before stdout or the atomic env
replacement; SDK diagnostics and error values stay private. Keep the SSM-only
path dependency-free beyond host Python. See README for provisioning/rollback.

`login_broker.py` is the one exception that touches login items: a host systemd
service that fills a tagged 1Password login into an owned Browserbase session and
returns status only. Never return or log a value, never relax its tag, session-owner
or host checks, and never move it into a container. See README.

The optional Brain adapter (`brain_readonly_adapter.py`) can serve a read-only
private snapshot with four tools and `sourceObservedAt`. Its cache and unchanged
renderer stay outside Git; never call the Brain collector, auto-refreshing load,
capture or search from snapshot mode. See the EC2 README.

`Dockerfile.memory-profile` is a two-file overlay of reviewed PR198 onto a verified
live gateway base. Export only the pinned source files into its build context.
Do not replace the base with latest main or infer a global model-policy change.

Production pins `memory.model_name` to the existing `claude-haiku-5-5` host profile
after checking backend override absence. Preserve private/shared memory scope and
the administrator's chat default; restart through the existing unit to rebuild
the cached manager. See README for readback, rollback and the quiet-window gate.
