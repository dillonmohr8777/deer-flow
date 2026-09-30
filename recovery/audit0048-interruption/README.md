# Audit0048 interruption repair — source only

The frozen V4 installer's outer CLI catches `Exception`, so a first `KeyboardInterrupt`
or `SystemExit` after candidate creation skips its owned-candidate fail-stop and stopped
receipt. This patch catches `BaseException` at that existing cleanup boundary and then
re-raises. It preserves the immutable ID/image/nonce/project/service ownership checks,
the no-recreation short circuit, and every migration, journal and preservation gate.

Original owner: `01a0f29b-0900-7281-90d6-b6621ec9e29a`.
Recovery worker: `/root/momobot_review` under the sole September 30 coordinator.
Base source commit: `aa4e4a08c0dbe0ad0bea0cbb62ab54f1369500ce`.

This directory is a reviewable patch and regression bundle. It is **not an installation
packet or an execution approval**. The frozen original is deliberately not modified:

- Original packet SHA256: `4018a2e7143ffe192e423d9b933b231ffb2ee8abe87064e211b2ef52cc86c89a`.
- Original `install.py` SHA256: `0bbfef91337f7fed44be772b95b3d8ccd9bd7e88e22488e4e3d807e28579c1d2`.
- The patch changes exactly one exception clause. Tests verify that exact original hash
  before loading the source, apply the patch in memory, and prohibit live Docker calls.

## Verification

`test_interruption.py` has eight cases: two negative controls reproduce the original
gap; six corrected cases cover `KeyboardInterrupt`, `SystemExit` and ordinary failures
both before and after candidate creation. They verify the same exception object is
re-raised, only the owned immutable ID is stopped, stopped state is read back, and no
restart/restore/retry/provider call occurs. All eight pass. The existing 97 V4 tests
also pass against the patched code. Eight audit migration tests pass using this exact
source checkout with explicit harness/extension Python paths. Ruff, format, Pyright and
compile checks pass within the original packet's declared check scope.

Run the added offline regressions from any directory:

```sh
/Users/dillonmohr/code/_worktrees/momo-browser-worker-integration-20260930/backend/.venv/bin/python -m pytest -q -p no:cacheprovider /Users/dillonmohr/code/_worktrees/momo-audit0048-interruption-20260930/recovery/audit0048-interruption/test_interruption.py
```

The completed, bounded Astra Ultrafast critique accepted this narrow source change.
It received the actual outer boundary and described cleanup contract and reported
tests; it did not independently read the full driver or execute tests. The native
recovery worker performed the full driver review and tests. The critique cost
`$0.101880`, with `$2.535230` left in the original owner's `$5` allocation and no
outstanding Ultrafast reservations at readback.

## Limits and held operations

This does not protect against SIGKILL, default SIGTERM, host/daemon crash, or repeated
interruption during cleanup. A cleanup or receipt-write failure can prevent the receipt
or replace the original propagated exception. Ordinary fail-stop transport failures
remain explicit manual-reconciliation outcomes; a failed stop is never reported as a
verified stop. These are preserved limits, not new claims of crash resilience.

V4 is rejected unchanged because of the reproduced interruption gap. Future use needs
the repair incorporated into a new source packet, a new freeze binding, independent
packet acceptance and a separately authorized exact operation. Recovery authorization
does not permit installation/cutover, a fresh live baseline, provider activation, retry,
reset, bypass, replacement cycle, downgrade, or any alteration of the separate uncertain
`$0.264` provider reservation. No such action was performed.

Complete evidence: `/Users/dillonmohr/Documents/Codex/2026-09-30/codex-desktop-recovery/momobot-recovery.md`.
