"""Fleet template library loader (Momentum fleet feature).

Templates live under ``fleet/templates/<template_id>/`` at the project root:
``template.yaml`` (id, version, name, description, default model, skills,
tool groups, MCP plugin ids, a suggested cron+timezone schedule, and an
acceptance criteria list) plus ``SOUL.md`` (the agent's instructions, with
``{client_name}``-style placeholders filled in at stamping time).

This mirrors two existing conventions rather than inventing a third: the
directory-per-item, ``config.yaml`` + ``SOUL.md`` shape already used by
``fleet/agents/<name>/`` (see ``backend/tests/test_momentum_agent_fleet.py``),
and the strict, ``extra="forbid"`` pydantic validation style used elsewhere in
this config package (e.g. ``AgentModelSettings``). ``fleet/agents/`` is a
separate, pre-existing system (engineering-role agents for building DeerFlow
itself); this module never reads or writes it.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from deerflow.config.agents_config import AGENT_NAME_PATTERN, validate_agent_name
from deerflow.config.runtime_paths import project_root
from deerflow.scheduler.schedules import normalize_cron_expression, validate_timezone

TEMPLATE_MANIFEST_FILENAME = "template.yaml"
SOUL_FILENAME = "SOUL.md"


class FleetTemplateError(ValueError):
    """A fleet template directory is missing, malformed, or fails validation.

    Always carries an actionable, human-readable message (which template,
    which file, what was wrong) rather than a bare pydantic traceback.
    """


class FleetTemplateSchedule(BaseModel):
    """The template's suggested schedule: a cron expression plus an IANA timezone."""

    model_config = ConfigDict(extra="forbid")

    cron: str = Field(min_length=1, description="5-field cron expression, e.g. '0 8 * * 1'.")
    timezone: str = Field(min_length=1, description="IANA timezone name, e.g. 'America/New_York'.")

    @field_validator("cron")
    @classmethod
    def _validate_cron(cls, value: str) -> str:
        try:
            normalized = normalize_cron_expression(value)
            croniter(normalized)
        except ValueError as exc:
            raise ValueError(f"invalid cron expression {value!r}: {exc}") from exc
        return normalized

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        return validate_timezone(value)


class FleetTemplate(BaseModel):
    """Validated contents of one ``fleet/templates/<template_id>/template.yaml``."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, description="Template id; must match the directory name.")
    version: str = Field(min_length=1, description="Template version, e.g. '1'.")
    name: str = Field(min_length=1, description="Human-readable template name.")
    description: str = Field(min_length=1, description="What this template's agent does.")
    model: str = Field(min_length=1, description="Default model name for a stamped agent.")
    skills: list[str] = Field(default_factory=list, description="Skill ids this agent may use.")
    tool_groups: list[str] = Field(default_factory=list, description="Tool group names this agent may use.")
    mcp_plugins: list[str] = Field(default_factory=list, description="MCP installation ids this agent may use.")
    schedule: FleetTemplateSchedule
    acceptance_criteria: list[str] = Field(min_length=1, description="What 'done' looks like for one run of this agent.")

    # Not part of template.yaml; populated from the sibling SOUL.md by the
    # loader. Kept on the model so callers have one object to pass around.
    soul: str = ""

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        validate_agent_name(value)
        return value

    def render_soul(self, *, client_name: str) -> str:
        """Fill the ``{client_name}`` placeholder in the SOUL.md body.

        A literal substring replace, not ``str.format``; SOUL.md is free-form
        prose that may contain unrelated curly braces (a markdown code sample,
        an aside), and those must not be mistaken for format fields.
        """
        return self.soul.replace("{client_name}", client_name)


def templates_root() -> Path:
    """Return the ``fleet/templates`` directory under the project root."""
    return project_root() / "fleet" / "templates"


def _load_one(template_dir: Path) -> FleetTemplate:
    template_id = template_dir.name
    manifest_path = template_dir / TEMPLATE_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise FleetTemplateError(f"Fleet template {template_id!r} is missing {TEMPLATE_MANIFEST_FILENAME} (expected at {manifest_path})")

    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise FleetTemplateError(f"Fleet template {template_id!r}: {TEMPLATE_MANIFEST_FILENAME} is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise FleetTemplateError(f"Fleet template {template_id!r}: {TEMPLATE_MANIFEST_FILENAME} must be a YAML mapping, got {type(raw).__name__}")

    try:
        template = FleetTemplate.model_validate(raw)
    except ValidationError as exc:
        raise FleetTemplateError(f"Fleet template {template_id!r} failed validation: {exc}") from exc

    if template.id != template_id:
        raise FleetTemplateError(f"Fleet template directory {template_id!r} declares id {template.id!r} in {TEMPLATE_MANIFEST_FILENAME}; the directory name and id must match")

    soul_path = template_dir / SOUL_FILENAME
    soul = soul_path.read_text(encoding="utf-8") if soul_path.is_file() else ""
    return template.model_copy(update={"soul": soul})


def load_fleet_templates() -> list[FleetTemplate]:
    """Load and validate every template under ``fleet/templates/``, sorted by id.

    An empty or absent ``fleet/templates/`` directory returns an empty list
    rather than raising; the catalog simply has nothing to offer yet. A
    malformed template directory raises :class:`FleetTemplateError` (this is
    a deployment's own template library, curated by operators, so a bad file
    should fail loudly rather than being silently skipped).
    """
    root = templates_root()
    if not root.is_dir():
        return []
    return [_load_one(entry) for entry in sorted(root.iterdir()) if entry.is_dir() and (entry / TEMPLATE_MANIFEST_FILENAME).is_file()]


def load_fleet_template(template_id: str) -> FleetTemplate | None:
    """Load and validate one template by id, or return ``None`` if it does not exist.

    Rejects a ``template_id`` that cannot possibly be a directory name under
    ``AGENT_NAME_PATTERN`` (e.g. containing ``/`` or ``..``) before it ever
    touches the filesystem, the same trust boundary ``validate_agent_name``
    enforces for agent names.
    """
    if not AGENT_NAME_PATTERN.fullmatch(template_id):
        return None
    template_dir = templates_root() / template_id
    if not template_dir.is_dir():
        return None
    return _load_one(template_dir)
