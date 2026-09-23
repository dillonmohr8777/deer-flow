# DeerFlow recovery: 2026-09-21/22

## What happened

An ~8-hour design and integration run ("momentum-integrate-20260921") was built into
Docker images, and the working tree it came from was then deleted. The work existed
**only inside the running containers**. It was in no git branch, no worktree, and no
backup directory on this machine.

Scale: **147 files, +10,536 lines**, including entire features and their tests.

A container survives a daemon restart (confirmed later the same night, when Docker
Desktop stopped and relaunching it brought everything straight back). What a container
does not survive is `docker system prune`, a disk-space reclaim, or a rebuild that
reuses the same tag. Any of those would have destroyed the work with no warning and no
recovery path. The exposure was real even though the mild failure mode is what actually
happened tonight.

## How it was found

`GET /api/v1/auth/setup-status` returned `needs_setup:false`, which contradicted the
assumption that first-run auth was incomplete. Chasing why led to the container/disk
comparison, which surfaced `paper.css` and `invite.module.css` inside the frontend
image and nowhere on disk.

The compose labels were actively misleading: `com.docker.compose.project.working_dir`
pointed at `deer-flow/docker`, and `config_files` listed four compose files across two
checkouts. Neither checkout was the actual source.

## Recovered

Branch `recover/momentum-integrate-20260921`, pushed to the `fork` remote.
(`origin` is bytedance upstream. Never push recovery work there.)

| commit | contents |
|---|---|
| `34f67df6` | 147 files of source, extracted verbatim from the live containers |
| `114e2a78` | `qrcode.react@4.2.0`, installed in the image but missing from `package.json` |
| `9309e138` | 15 backend test files + 38 updates |
| `2d9368e3` | 15 frontend test files + 10 updates |
| `aa97d90e` | `scripts/benchmark/deermem_scope_isolation/`, `docs/RUN_INTERACTION_POLICY.md`, `backend/Dockerfile` media-types layer |
| `165cc803` | fixed a migration test whose head-identity assertion rotted when the chain advanced |

### Features that came back

- **Workspace invitations**: `gateway/routers/invitations.py`, `app/invite/`,
  `persistence/organizations/invitation.py`, migration `0029_shared_workspace`
- **Shared workspaces**: `gateway/routers/workspaces.py`, `workspace-selector.tsx`
- **Managed models**: `gateway/routers/managed_models.py`, `model-settings-page.tsx`
- **Workspace branding**: `gateway/routers/workspace_branding.py`,
  `brand-signature.tsx`, migration `0030_workspace_branding`
- **Appearance system**: `appearance-provider.tsx`, `appearance-preferences.ts`,
  `workspace-appearance.tsx`
- **Paper design treatment**: `styles/paper.css` (324 lines), `cut-paper.tsx`,
  `treatment.ts`, `styles/fonts.css` (182 lines)
- **Momo avatar**: `momo-avatar.tsx` + module.css
- **WeChat QR login**: `channels/wechat_qr_login.py`,
  `wechat-qr-{login,completion}.tsx`

## Verification

| check | result |
|---|---|
| `tsc --noEmit` | clean |
| `pnpm build` | exit 0, full production build |
| frontend unit suite | **1,948 tests, 0 failures** |
| backend feature suites | 98 passed |
| `test_bench_deermem_scope_isolation` + `test_interaction_policy` | 31 passed |
| migration suite | 187 passed, 2 failed (both pre-existing at 83f4e423, verified in a scratch worktree, untouched by the recovery) |
| gateway image rebuilt from branch vs running | **735 Python files, 0 diff** |
| frontend image rebuilt from branch vs running | **623 files, 0 diff** |
| secret scan of the diff | clean |
| full backend suite | in progress at time of writing |

## The find a source diff could not make

`backend/Dockerfile` was missing an apt layer installing `media-types`. Without it
Python's mimetypes registry is the minimal one:

```
running gateway : guess_type("a.xhtml") -> application/xhtml+xml
rebuilt (before) : guess_type("a.xhtml") -> None
rebuilt (after)  : guess_type("a.xhtml") -> application/xhtml+xml
```

`app/channels/wechat.py:1237` falls back to `application/octet-stream` when
`guess_type` returns None, so WeChat file MIME classification changed depending on how
the image was built. `octet-stream` is the conservative fallback, so this is a
correctness and consistency bug rather than an exploitable one. It is invisible to any
source-level comparison, though, because the difference is in the image layer, not the
tree.

Byte-identical source is not the same as an equivalent image. Check both.

## Collateral findings

- **The deploy worktree was dead weight and has been deleted.** It had 27 uncommitted
  files, all superseded by the recovery. Its single divergence was that it was
  *missing* the `workspace_branding` router. Nothing unique was stranded there;
  verified with a file-by-file diff before removal.
- **Auth was never broken.** Admin `admin@example.com` has existed since 2026-09-18.
  `register` returning 403 is `allow_registration: false` policy; `login` returning 403
  is the CSRF middleware working. Neither is a fault.
- **A single missing module was masking suite health.** The absent benchmark module
  failed `test_bench_deermem_scope_isolation.py` at *collection*, which under `-x`
  aborted every test after it.
- **~48GB of Docker disk reclaimed**, all verified safe first: 19.5GB build cache
  (pure derived data), plus superseded `deer-flow-*` images extracted and diffed
  against the recovery branch, each confirmed to hold zero files not already in git.
  Kept: the four running containers' images, both rollback tags, both
  recovered-verify tags, and infra images (provisioner, sandbox-network-proxy).

## Rollback

The pre-existing images are tagged and retained:

```
deer-flow-gateway:rollback-known-good-20260921
deer-flow-frontend:rollback-known-good-20260921
```

Images rebuilt and verified from the branch:

```
deer-flow-gateway:recovered-verify-20260921
deer-flow-frontend:recovered-verify-20260921
```

The running stack was **not** swapped. What is running is already correct, and the
rebuilt images are verified equivalent, so there is no benefit to swapping until you
choose to.

## Open

- **Login.** The browser pane sat on the sign-in screen with the email filled all
  night. The workspace and command-center design surfaces, and a live chat
  round-trip, are behind it. No password was typed or invented.
- **Landing and invite pages verified visually**: paper edges, blue grid, font stack,
  correct empty-token handling.
- **No PR opened.** A verbatim container snapshot is not a reviewable change set, and
  `fork/main` is 42 commits behind upstream. The reconciliation into a reviewable
  branch is separate work.
- **Momo avatar art is missing, not just unmapped.** `public/momentum/momos/` does
  not exist. The component expects SVG at that path; only 4 of 10 intended agent
  slugs have a confident roster-name mapping (`analytics`, `migration`, `verifier`,
  `research`). The other six were deliberately left unmapped by the original run.
  Every agent currently renders the procedural glyph fallback, which the code
  explicitly treats as correct until real art lands.

## Don't let this recur

Before rebuilding, pruning, or stopping DeerFlow containers, compare file counts
between the container and every checkout:

```
/app/frontend/src   /app/frontend/tests
/app/backend/app    /app/backend/packages   /app/backend/tests   /app/backend/scripts
```

Counts are the fast tell: the container had 746 backend tests against 732 on disk.
Also diff `package.json` and the Dockerfiles. Treat any image tag with no matching
checkout as unsaved work until proven otherwise.

Note: `docker cp` fails on the `.venv` symlinks on Windows ("a required privilege is
not held by the client"). Use:

```
docker exec <container> tar -cf - --exclude=.venv --exclude=__pycache__ -C /app/backend app packages tests | tar -xf - -C .
```
