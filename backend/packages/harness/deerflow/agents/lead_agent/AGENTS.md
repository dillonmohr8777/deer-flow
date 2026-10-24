# Lead-agent profile context

USER.md context is capped at 8 KiB of UTF-8 before HTML escaping. Preserve full
profiles within that budget, UTF-8-safe truncation with its marker above it, and
public-channel omission. Regressions live in `tests/test_lead_agent_prompt.py`.
Read only the resolved storage principal's profile; a missing scoped profile
stays empty and must never fall back to the process-global USER.md.
