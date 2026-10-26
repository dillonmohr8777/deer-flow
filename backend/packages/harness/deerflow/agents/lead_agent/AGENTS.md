# Lead-agent profile context

USER.md context is capped at 8 KiB of UTF-8 before HTML escaping. Preserve full
profiles within that budget, UTF-8-safe truncation with its marker above it, and
public-channel omission. Regressions live in `tests/test_lead_agent_prompt.py`.
Read only the resolved storage principal's profile; a missing scoped profile
stays empty and must never fall back to the process-global USER.md.

Max lead assembly adds `propose_action` to the tool ceiling only for authenticated
staff roles (`user`, `exec`, `admin`) outside channel and subagent runs, before
normal role authorization. Keep the built-in client ceiling unchanged and pass
the same staff ceiling to runtime tool policy. Exclude proposal filing from
Max's delegated task/batch ceiling. Proposal filing never grants approval
authority. Regressions: `tests/test_momobot_max_assembly.py` and
`tests/test_subagent_tool_ceiling.py`.
