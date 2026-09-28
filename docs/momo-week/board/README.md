# Momo Week board

Routines coordinate by message, not by re-reading QUEUE.md and PROGRESS.md.

## Roles and inboxes

| Role | Inbox | Who |
|---|---|---|
| builder | `builder.md` | `momo-week` routine |
| designer | `designer.md` | `momo-week-design` routine |
| reviewer | `reviewer.md` | `momo-week-review` routine |
| chief | `chief.md` | interactive Claude with Dillon |
| dillon | `dillon.md` | Dillon: blockers, approvals, merges |

## Message format

Append to the recipient's inbox:

```
### 2026-09-28 14:10 UTC · builder → reviewer · e8 · handoff
PR #65 ready. Tests: <command> green. Look at <file:line>.
```

Types: `handoff`, `finding`, `question`, `blocked`, `done`, `ack`. Eight lines max. Link, don't paste.

## Every run

1. Read your inbox. Find your tasks with `grep -n '^- \[[ ~]\]' docs/momo-week/QUEUE.md`. Read PROGRESS.md with `tail -3` only.
2. Empty inbox and no open task in your section: stop. No commit, no PROGRESS line.
3. Handle messages before taking a task.
4. After any change, post one message to the next role (builder → reviewer, reviewer → builder, anyone → dillon when blocked).
5. Move handled messages to `archive/YYYY-MM.md` in the same commit.
6. Commit board files straight to `lane/momo-week` with QUEUE.md and PROGRESS.md.

No secrets, tokens, or client PII in messages.
