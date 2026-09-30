"""The public catalog is executable, concrete, bounded, and entirely synthetic."""

import json

import pytest
from jsonschema import Draft202012Validator

from deerflow.workflows.catalog import get_workflow, list_workflows, validate_inputs
from deerflow.workflows.errors import WorkflowInputError


def test_catalog_contains_100_momentum_and_20_personal_distinct_concrete_workflows():
    definitions = list_workflows()
    assert len(definitions) == 120
    assert sum(item.category != "personal" for item in definitions) == 100
    assert sum(item.category == "personal" for item in definitions) == 20
    assert len({item.id for item in definitions}) == 120
    assert len({item.title for item in definitions}) == 120
    assert len({json.dumps(item.input_schema, sort_keys=True) for item in definitions}) == 120
    assert len({json.dumps(item.output_schema, sort_keys=True) for item in definitions}) == 120
    assert len({tuple(item.acceptance) for item in definitions}) == 120
    for item in definitions:
        assert get_workflow(item.id) == item
        assert item.steps == ["validate", "research", "plan", "draft", "verify", "accept"]
        assert len(item.acceptance) >= 3
        assert item.example_inputs["brief"].startswith("SYNTHETIC")
        assert "placeholder" not in item.summary.lower()
        Draft202012Validator.check_schema(item.input_schema)
        Draft202012Validator.check_schema(item.output_schema)
        validate_inputs(item, item.example_inputs)


@pytest.mark.parametrize("definition", list_workflows(), ids=lambda item: item.id)
def test_every_workflow_rejects_missing_required_input_and_unknown_fields(definition):
    with pytest.raises(WorkflowInputError):
        validate_inputs(definition, {})
    with pytest.raises(WorkflowInputError):
        validate_inputs(definition, {**definition.example_inputs, "secret_override": "no"})


def test_browser_inputs_reject_private_urls_before_callback():
    definition = next(item for item in list_workflows() if item.requires_browser)
    for url in ["http://example.com", "https://localhost/", "https://127.0.0.1/", "https://[::1]/", "https://example.com@localhost/", "https://internal.local/", "https://169.254.169.254/"]:
        with pytest.raises(WorkflowInputError):
            validate_inputs(definition, {**definition.example_inputs, "source_urls": [url]})


def test_catalog_returns_independent_copies_and_unknown_id_fails():
    first = list_workflows()[0]
    first.input_schema["required"].clear()
    assert get_workflow(first.id).input_schema["required"]
    with pytest.raises(KeyError):
        get_workflow("unknown-workflow")
