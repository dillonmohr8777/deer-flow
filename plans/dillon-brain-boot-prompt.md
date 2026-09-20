# Dillon Brain — Chrome boot prompt

How to run: open `http://localhost:2026`, switch the agent selector in the chat
input bar to **Dillon Brain**, paste everything below the line, send.

(If the agent list does not show it yet, hard-refresh the page — the agent file
hot-reloads and the list refreshes on load.)

---

Boot sequence. Work in this order, then stand by as my orchestrator.

0. Confirm: `dillon-machine` is in your available skills and `/mnt/host/*` mounts
   are visible. If the skill is missing from your list, read
   `/app/skills/custom/dillon-machine/SKILL.md` directly, then continue.
1. Load the `dillon-machine` skill and read its `references/MAP.md` fully.
2. Run ONE `batch_task` with exactly these 3 independent scopes (nothing else
   in this batch). Each scope returns a compact brief: key paths + 5-line
   summary. No scope may touch another scope's paths.
   - Scope A (vault): `/mnt/host/repos/dillon-os/INDEX.md`,
     `System/operating-status.md`, `System/approval-queue.md`,
     `12_Brain/00_Home.md`. Report: current status, open queue items, where
     project records live. OUT of scope: automations, agents, skills, designs.
   - Scope B (automations + agents): `/mnt/host/codex-automations`,
     `/mnt/host/claude-agents`, `/mnt/host/codex-agents`. Report: how many of
     each, the 5 most recent Claude agents by file date, what each automation
     dir holds at top level. OUT of scope: vault, skills, designs, sessions.
   - Scope C (skills + designs): top-level `ls` counts of
     `/mnt/host/skills-codex`, `/mnt/host/skills-claude`,
     `/mnt/host/skills-agents`; read
     `/mnt/host/codex-docs/momentum-design-system/AUDIT.md` header only (first
     40 lines). Report: counts, how you will search the corpus, token source
     of truth + drift rule. OUT of scope: vault, automations, agents.
3. Synthesize the 3 briefs into one machine brief (max 40 lines), save it to
   `/mnt/host/outbox/boot-brief.md`, and reply in chat with: mount count you
   verified, brief highlights (10 lines max), the Windows path of the saved
   brief, and one sentence confirming you are standing by as orchestrator.
