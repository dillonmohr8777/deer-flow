### Fleet template library (`packages/harness/deerflow/fleet/`)

The template catalog for per-client agents: "an agent is a template plus a
client binding." Data files live at the **repo root** under
`fleet/templates/<template_id>/` (`template.yaml` + `SOUL.md`), resolved via
`project_root()` (`templates_root()` in `templates.py`), not under this
package. This is unrelated to the pre-existing `fleet/agents/` engineering-role
fleet (`test_momentum_agent_fleet.py`); never touch `fleet/agents/`,
`fleet/manifest.json`, or `fleet/evals/` from this module.

`load_fleet_templates()` / `load_fleet_template(id)` are the only entry points.
Both raise `FleetTemplateError` (a `ValueError`) with an actionable message on
a malformed template; `template.yaml` uses `extra="forbid"` pydantic models,
so an unknown field is a validation error, not a silently ignored key. A
template's `id` must equal its directory name. `schedule.cron` is validated
with the same `normalize_cron_expression()` / `croniter` used by
`scheduler/schedules.py`, and `schedule.timezone` with that module's
`validate_timezone()`; reuse those, do not re-implement cron/timezone checks
here.

Stamping (turning a template + a client into a real custom agent and a paused
scheduled task) is Gateway-layer, not this package: see
`app/gateway/routers/clients.py`'s `POST /{client_id}/agents`.
