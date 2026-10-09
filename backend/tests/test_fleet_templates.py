"""Tests for the fleet template library loader (deerflow.fleet.templates)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from deerflow.fleet import FleetTemplateError, load_fleet_template, load_fleet_templates, templates_root

VALID_MANIFEST = {
    "id": "weekly-client-report",
    "version": "1",
    "name": "Weekly Client Report",
    "description": "Pulls the week's numbers into a short report draft.",
    "model": "openrouter-sonnet-5",
    "skills": ["data-analysis"],
    "tool_groups": ["web_search"],
    "mcp_plugins": [],
    "schedule": {"cron": "0 8 * * 1", "timezone": "America/New_York"},
    "acceptance_criteria": ["Covers the prior 7 days only."],
}


def _write_template(root: Path, template_id: str, manifest: dict, soul: str = "You are helpful.\n") -> Path:
    template_dir = root / "fleet" / "templates" / template_id
    template_dir.mkdir(parents=True)
    (template_dir / "template.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    (template_dir / "SOUL.md").write_text(soul, encoding="utf-8")
    return template_dir


@pytest.fixture()
def project_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(tmp_path))
    return tmp_path


def test_templates_root_is_under_project_root(project_root) -> None:
    assert templates_root() == project_root / "fleet" / "templates"


def test_load_fleet_templates_empty_when_directory_absent(project_root) -> None:
    assert load_fleet_templates() == []


def test_load_valid_template_round_trips_every_field(project_root) -> None:
    _write_template(project_root, "weekly-client-report", VALID_MANIFEST, soul="Hello {client_name}.\n")

    template = load_fleet_template("weekly-client-report")

    assert template is not None
    assert template.id == "weekly-client-report"
    assert template.version == "1"
    assert template.name == "Weekly Client Report"
    assert template.model == "openrouter-sonnet-5"
    assert template.skills == ["data-analysis"]
    assert template.tool_groups == ["web_search"]
    assert template.mcp_plugins == []
    assert template.schedule.cron == "0 8 * * 1"
    assert template.schedule.timezone == "America/New_York"
    assert template.acceptance_criteria == ["Covers the prior 7 days only."]
    assert template.soul == "Hello {client_name}.\n"
    rendered = template.render_soul(client_name="Acme")
    assert rendered.startswith("Hello Acme.\n")
    assert "Covers the prior 7 days only." in rendered
    assert "UNVERIFIED" in rendered


def test_render_soul_preserves_braces_and_fills_client_in_criteria(project_root) -> None:
    manifest = {**VALID_MANIFEST, "acceptance_criteria": ['Reconcile {client_name} totals with {"amount": 12}.']}
    _write_template(project_root, "weekly-client-report", manifest, soul='Keep {"a": 1} for {client_name}.')
    template = load_fleet_template("weekly-client-report")
    rendered = template.render_soul(client_name="Acme")
    assert 'Keep {"a": 1} for Acme.' in rendered
    assert 'Reconcile Acme totals with {"amount": 12}.' in rendered
    assert template.acceptance_criteria == manifest["acceptance_criteria"]


def test_load_fleet_templates_lists_sorted_by_id(project_root) -> None:
    _write_template(project_root, "review-replies", {**VALID_MANIFEST, "id": "review-replies"})
    _write_template(project_root, "ai-search-visibility", {**VALID_MANIFEST, "id": "ai-search-visibility"})

    templates = load_fleet_templates()

    assert [t.id for t in templates] == ["ai-search-visibility", "review-replies"]


def test_load_fleet_template_unknown_id_returns_none(project_root) -> None:
    assert load_fleet_template("does-not-exist") is None


@pytest.mark.parametrize("bad_id", ["../escape", "has/slash", "has space", ""])
def test_load_fleet_template_rejects_unsafe_ids_without_raising(project_root, bad_id) -> None:
    assert load_fleet_template(bad_id) is None


def test_load_fleet_template_missing_manifest_raises(project_root) -> None:
    template_dir = project_root / "fleet" / "templates" / "weekly-client-report"
    template_dir.mkdir(parents=True)
    (template_dir / "SOUL.md").write_text("soul", encoding="utf-8")

    with pytest.raises(FleetTemplateError, match="missing template.yaml"):
        load_fleet_template("weekly-client-report")


def test_load_fleet_template_rejects_unknown_field(project_root) -> None:
    _write_template(project_root, "weekly-client-report", {**VALID_MANIFEST, "unexpected_field": "nope"})

    with pytest.raises(FleetTemplateError, match="failed validation"):
        load_fleet_template("weekly-client-report")


def test_load_fleet_template_rejects_id_directory_mismatch(project_root) -> None:
    _write_template(project_root, "weekly-client-report", {**VALID_MANIFEST, "id": "some-other-id"})

    with pytest.raises(FleetTemplateError, match="must match"):
        load_fleet_template("weekly-client-report")


def test_load_fleet_template_rejects_invalid_cron(project_root) -> None:
    manifest = {**VALID_MANIFEST, "schedule": {"cron": "not a cron", "timezone": "UTC"}}
    _write_template(project_root, "weekly-client-report", manifest)

    with pytest.raises(FleetTemplateError, match="failed validation"):
        load_fleet_template("weekly-client-report")


def test_load_fleet_template_rejects_invalid_timezone(project_root) -> None:
    manifest = {**VALID_MANIFEST, "schedule": {"cron": "0 8 * * 1", "timezone": "Not/AZone"}}
    _write_template(project_root, "weekly-client-report", manifest)

    with pytest.raises(FleetTemplateError, match="failed validation"):
        load_fleet_template("weekly-client-report")


def test_load_fleet_template_rejects_empty_acceptance_criteria(project_root) -> None:
    manifest = {**VALID_MANIFEST, "acceptance_criteria": []}
    _write_template(project_root, "weekly-client-report", manifest)

    with pytest.raises(FleetTemplateError, match="failed validation"):
        load_fleet_template("weekly-client-report")


def test_load_fleet_template_rejects_malformed_yaml(project_root) -> None:
    template_dir = project_root / "fleet" / "templates" / "weekly-client-report"
    template_dir.mkdir(parents=True)
    (template_dir / "template.yaml").write_text("id: [unterminated", encoding="utf-8")

    with pytest.raises(FleetTemplateError, match="not valid YAML"):
        load_fleet_template("weekly-client-report")


def test_load_fleet_template_missing_soul_is_empty_string(project_root) -> None:
    template_dir = project_root / "fleet" / "templates" / "weekly-client-report"
    template_dir.mkdir(parents=True)
    (template_dir / "template.yaml").write_text(yaml.safe_dump(VALID_MANIFEST), encoding="utf-8")

    template = load_fleet_template("weekly-client-report")

    assert template is not None
    assert template.soul == ""


class TestRealTemplateLibrary:
    """Load the actual fleet/templates/ shipped in this repo, end to end."""

    @pytest.fixture(autouse=True)
    def _real_project_root(self, monkeypatch):
        monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(Path(__file__).resolve().parents[2]))

    def test_all_four_shipped_templates_validate(self) -> None:
        templates = load_fleet_templates()
        ids = {t.id for t in templates}
        assert ids == {
            "weekly-client-report",
            "ai-search-visibility",
            "content-drafts",
            "review-replies",
        }
        for template in templates:
            assert template.soul.strip(), f"{template.id} has an empty SOUL.md"
            assert "{client_name}" in template.soul, f"{template.id} SOUL.md has no {{client_name}} placeholder"
            # No hyphen-as-punctuation banned characters (em dash, en dash, " -- ").
            assert "—" not in template.soul
            assert "–" not in template.soul
            assert " -- " not in template.soul
