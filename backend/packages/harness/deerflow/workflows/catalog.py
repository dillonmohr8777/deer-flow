"""Concrete bounded JSON-schema workflow definitions and input admission."""

from __future__ import annotations

import copy
import ipaddress
import json
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from pydantic import BaseModel, ConfigDict

from deerflow.workflows.errors import WorkflowInputError
from deerflow.workflows.examples import example_field
from deerflow.workflows.recipes import BROWSER_IDS, PERSONAL_RECIPES, RECIPES

MAX_INPUT_BYTES = 48_000
MAX_OUTPUT_BYTES = 48_000


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    category: str
    summary: str
    input_schema: dict
    output_schema: dict
    steps: list[str]
    acceptance: list[str]
    example_inputs: dict
    requires_browser: bool


def _text(description: str, *, limit: int = 6000) -> dict:
    return {"type": "string", "minLength": 1, "maxLength": limit, "description": description}


def _definition(category: str, row: str) -> WorkflowDefinition:
    identifier, title, input_names, output_names, instruction, criteria = row.split("|")
    fields = input_names.split(",")
    browser = category == "seo" or identifier in BROWSER_IDS
    properties = {"brief": _text(f"Business context and purpose for {title}; use only authorized source material.")}
    subject = "a fictional personal creative or technical project" if category == "personal" else "fictional Cedar Demo Studio"
    examples = {"brief": f"SYNTHETIC demonstration for {subject}: {title}. These examples contain no real client data."}
    for name in fields:
        properties[name] = _text(f"Verified {name.replace('_', ' ')} relevant to {title}; explicitly describe missing facts.")
        examples[name] = example_field(name, title=title, category=category)
    if browser:
        properties["source_urls"] = {
            "type": "array",
            "items": {"type": "string", "format": "uri", "maxLength": 2048},
            "minItems": 1,
            "maxItems": 3,
            "uniqueItems": True,
            "description": "Public HTTPS source URLs; browser actions are read-only.",
        }
        examples["source_urls"] = ["https://example.com/"]
    output_properties = {
        "workflow_id": {"type": "string", "const": identifier},
        "status": {"type": "string", "const": "draft"},
        "assumptions": {"type": "array", "items": _text("Explicit uncertainty or unsupported assumption.", limit=1000), "maxItems": 10},
        "evidence_references": {"type": "array", "items": _text("input:<field> or a returned browser evidence reference.", limit=2048), "minItems": 1, "maxItems": 20, "uniqueItems": True},
    }
    for name in output_names.split(","):
        limit = {"headlines": 30, "descriptions": 90, "meta_descriptions": 160}.get(name, 1500)
        output_properties[name] = {"type": "array", "items": _text(f"Specific {name.replace('_', ' ')} for {title} grounded in the admitted inputs.", limit=limit), "minItems": 1, "maxItems": 12, "uniqueItems": True}
    acceptance = criteria.split(";")
    return WorkflowDefinition(
        id=identifier,
        title=title,
        category=category,
        summary=instruction,
        input_schema={"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False},
        output_schema={"type": "object", "properties": output_properties, "required": list(output_properties), "additionalProperties": False},
        steps=["validate", "research", "plan", "draft", "verify", "accept"],
        acceptance=acceptance,
        example_inputs=examples,
        requires_browser=browser,
    )


_CATALOG = {definition.id: definition for category, rows in {**RECIPES, "personal": PERSONAL_RECIPES}.items() for row in rows.strip().splitlines() if row.strip() for definition in [_definition(category, row)]}
if len(_CATALOG) != 120 or sum(definition.category != "personal" for definition in _CATALOG.values()) != 100:
    raise RuntimeError("workflow_catalog_must_have_100_momentum_and_20_personal_definitions")


def get_workflow(identifier: str) -> WorkflowDefinition:
    return _CATALOG[identifier].model_copy(deep=True)


def list_workflows() -> list[WorkflowDefinition]:
    return [definition.model_copy(deep=True) for definition in _CATALOG.values()]


def _public_https(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme != "https" or parsed.username is not None or parsed.password is not None or parsed.port not in (None, 443) or not host or "." not in host or host.endswith((".local", ".internal", ".localhost")):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return host != "localhost"
    except (ValueError, TypeError):
        return False


def validate_inputs(definition: WorkflowDefinition, inputs: dict) -> dict:
    """Validate before checkpoint/provider work; return an independent plain copy."""
    try:
        encoded = json.dumps(inputs, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_INPUT_BYTES:
            raise WorkflowInputError("workflow_input_too_large")
        Draft202012Validator(definition.input_schema, format_checker=FormatChecker()).validate(inputs)
        if definition.requires_browser and not all(_public_https(url) for url in inputs["source_urls"]):
            raise WorkflowInputError("workflow_requires_public_https_sources")
    except (TypeError, ValueError, ValidationError) as error:
        if isinstance(error, WorkflowInputError):
            raise
        raise WorkflowInputError("workflow_input_schema_invalid") from None
    return copy.deepcopy(inputs)
