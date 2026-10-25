# MomoBot Linux workspaces

Stopped-by-default, copy-on-write Linux environments paired with the existing fleet host runner. One pinned image supplies tools; OrbStack clones one quiesced golden volume per environment. The durable subagent batch remains the only queue.

## Contract

- Native Linux/arm64 or Linux/amd64 base, pinned by manifest digest and recorded by image ID.
- Non-root execution, no network by default, all capabilities dropped, `no-new-privileges`, 512 MiB memory with no extra swap, one CPU and 128 PIDs.
- Independent container writable state and cloned named volume. Client mounts are explicit, read-only and contained by an operator-configured root for that exact client after symlink resolution. Missing roots and escapes fail closed before volume cloning or container creation. Client data, sessions, models and credentials never enter the base.
- Canonical fleet item IDs dedupe work across attempts. Changed commands or client scope fail closed. Environment locks serialize execution; three slot locks bound active workers, including running or cleanup-pending work after a manager restart.
- Jobs checkpoint, execute, export hash manifests and stop. Command completion is separate from cleanup: stop failure retains capacity and never publishes success, and cleanup-only retries do not replay completed commands. Start and reused-environment execution enforce the disk floor. Recovery requires an exact environment/job scope and skips a live execution lock.
- Gateway `workspace` descriptors carry `environment_id`, bounded `command`, `timeout_seconds` and optional `client_path`. Workspace batches reject `max_running_items > 3` and require an admitted client for client mounts. Host operators configure `workspace_client_roots` as a client-ID-to-absolute-directory map; the CLI equivalent is repeated `--client-root CLIENT_ID=PATH`. No root is inferred from the submitted descriptor.

## Commands

```sh
python3 fleet/workspaces/momo_workspaces.py build
python3 fleet/workspaces/momo_workspaces.py create pilot-001 synthetic-canary
python3 fleet/workspaces/momo_workspaces.py batch pilot synthetic-canary --count 100
python3 fleet/workspaces/momo_workspaces.py start pilot-001
python3 fleet/workspaces/momo_workspaces.py job pilot-001 /absolute/job.json
python3 fleet/workspaces/momo_workspaces.py save pilot-001
python3 fleet/workspaces/momo_workspaces.py stop pilot-001
python3 fleet/workspaces/momo_workspaces.py status
python3 fleet/workspaces/momo_workspaces.py measure
python3 fleet/workspaces/momo_workspaces.py recover pilot-001 canonical-item-id
python3 fleet/workspaces/momo_workspaces.py cleanup pilot-001
```

A job contains exactly `schema_version`, `job_id`, `client_id`, `attempt`, `command`, and `timeout_seconds`. `command` is an argv list, never a shell string.

The implementation reached 100 saved stopped environments on OrbStack. Three active 64 MiB workloads used approximately 84 MiB each; a fourth simultaneous job was rejected and later completed. Docker's aggregate writable container data increased by less than 1 MB across the batch. Host free-disk and OrbStack RSS measurements remain temporal because other services were running.

`inference.example.json` is disabled and contains no credential. Rotate any exposed provider key before storing its replacement in 1Password; never write it to `CLAUDE.md`, Git, image layers, job payloads or logs. No production deployment or live fleet submission is implied by local verification.

See the paired host runner's `fleet/workspaces/README.md` for the full capability map, measurements, REA evidence, security boundary and rollback procedure.
