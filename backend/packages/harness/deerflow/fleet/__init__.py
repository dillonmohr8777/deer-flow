"""Fleet template library: versioned per-client agent templates.

Public entry point: :func:`load_fleet_templates` / :func:`load_fleet_template`.
See ``templates.py`` for the file format and ``AGENTS.md`` for conventions.
"""

from __future__ import annotations

from deerflow.fleet.templates import (
    FleetTemplate,
    FleetTemplateError,
    FleetTemplateSchedule,
    load_fleet_template,
    load_fleet_templates,
    templates_root,
)

__all__ = [
    "FleetTemplate",
    "FleetTemplateError",
    "FleetTemplateSchedule",
    "load_fleet_template",
    "load_fleet_templates",
    "templates_root",
]
