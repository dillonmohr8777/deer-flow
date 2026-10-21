"""The role tiers from config.example.yaml's commented `authorization:` block, parsed.

Tests build their RBAC policy from the example itself, so the documented tiers
and the behaviour tests cannot drift apart.
"""

from __future__ import annotations

from pathlib import Path

import yaml

EXAMPLE = Path(__file__).resolve().parents[2] / "config.example.yaml"


def example_roles() -> dict:
    lines = EXAMPLE.read_text(encoding="utf-8").splitlines()
    block = []
    for line in lines[lines.index("# authorization:") :]:
        if not line.startswith("#"):
            break
        block.append(line[2:] if line.startswith("# ") else "")
    return yaml.safe_load("\n".join(block))["authorization"]["provider"]["config"]["roles"]


def example_authorization(*, fail_closed: bool = True) -> dict:
    """An `authorization:` config section enabling the example's RBAC tiers."""
    return {
        "enabled": True,
        "fail_closed": fail_closed,
        "default_role": "user",
        "provider": {"use": "deerflow.authz.rbac:RbacAuthorizationProvider", "config": {"roles": example_roles()}},
    }
