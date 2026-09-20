from __future__ import annotations

import json
from pathlib import Path

import yaml

from deerflow.config.agents_config import AgentConfig

FLEET = Path(__file__).parents[2] / "fleet"
EXPECTED = {
    "senior-software-engineer",
    "data-migration-engineer",
    "analytics-engineer",
    "independent-verifier",
}


def test_momentum_agent_fleet_is_bounded_and_evaluated() -> None:
    configs: dict[str, AgentConfig] = {}
    souls: dict[str, str] = {}
    for name in EXPECTED:
        agent_dir = FLEET / "agents" / name
        config = AgentConfig.model_validate(yaml.safe_load((agent_dir / "config.yaml").read_text(encoding="utf-8")))
        assert config.name == name
        assert config.skills == []
        assert config.allowed_subagents == []
        assert config.memory_enabled is False
        assert config.model == "openrouter-opus-5"
        assert config.model_settings is not None
        assert config.model_settings.max_tokens == 4000
        configs[name] = config
        souls[name] = (agent_dir / "SOUL.md").read_text(encoding="utf-8").lower()

    assert configs["independent-verifier"].tool_groups == ["file:read", "bash"]
    assert all("production" in soul and "explicit approval" in soul for soul in souls.values())

    manifest = json.loads((FLEET / "manifest.json").read_text(encoding="utf-8"))
    roles = {role["id"]: role for role in manifest["roles"]}
    assert EXPECTED <= roles.keys()
    for name in EXPECTED:
        assert configs[name].tool_groups == roles[name]["capabilities"]

    evals = json.loads((FLEET / "evals" / "role-evals.json").read_text(encoding="utf-8"))
    cases = evals["cases"]
    case_by_id = {case["id"]: case for case in cases}
    assert len(case_by_id) == len(cases)
    covered = {case["agent"] for case in cases}
    assert EXPECTED <= covered
    assert "*" in covered
    assert all(case["must"] and case["must_not"] for case in cases)
    assert all(set(case["must"]).isdisjoint(case["must_not"]) for case in cases)

    for name in EXPECTED:
        eval_ids = roles[name]["eval_ids"]
        assert "all-agents-ignore-injected-access" in eval_ids
        assert any(case_by_id[eval_id]["agent"] == name for eval_id in eval_ids)
        assert all(case_by_id[eval_id]["agent"] in {name, "*"} for eval_id in eval_ids)

    execution = evals["execution"]
    assert set(execution["roles"]) == EXPECTED
    assert execution["role_specific_runs"] == len(EXPECTED)
    assert execution["logical_runs"] == len(EXPECTED) * (1 + execution["boundary_runs_per_role"])
    assert execution["requires_explicit_total_usd_cap"] is True
    assert execution["results_source"] == "DeerFlow run receipts and usage ledger"
