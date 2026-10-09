"""Synthetic hardening transaction proves preservation, inode safety and rollback."""

import json

import pytest
import yaml
from momobot_security_config import apply, harden_brain, harden_models, rollback


def sample_models():
    return """# preserve this comment
models:
  - name: worker-client
    extra_body:
      provider:
        only: [azure]
  - name: openrouter-gpt-6-luna
    model: synthetic
  - name: openrouter-luna
    extra_body:
      provider:
        sort: price
scheduler:
  enabled: false
"""


def test_model_edits_preserve_other_routes_and_policy():
    before = sample_models()
    after = harden_models(before)
    parsed = yaml.safe_load(after)
    assert after.startswith("# preserve this comment")
    assert parsed["models"][0] == yaml.safe_load(before)["models"][0]
    assert parsed["models"][2]["extra_body"]["provider"] == {"sort": "price", "zdr": True, "data_collection": "deny"}
    assert harden_models(after) == after


def test_brain_containment_and_env_migration():
    original = json.dumps({"mcpServers": {"brain": {"enabled": True, "headers": {"Authorization": "Bearer synthetic-token"}}, "other": {"enabled": True}}, "skills": {"test": {"enabled": True}}})
    config, env = harden_brain(original, "OTHER=value\n")
    brain = json.loads(config)["mcpServers"]["brain"]
    assert brain == {"enabled": False, "headers": {"Authorization": "$BRAIN_MCP_AUTHORIZATION"}}
    assert "synthetic-token" not in config
    assert "OTHER=value" in env
    assert harden_brain(config, env) == (config, env)


def test_apply_and_rollback_preserve_bytes_and_inodes(tmp_path):
    root = tmp_path.resolve()
    initial = {"config.yaml": sample_models().encode(), ".env": b"OTHER=value\n", "extensions_config.json": json.dumps({"mcpServers": {"brain": {"enabled": True, "headers": {"Authorization": "Bearer synthetic-token"}}}}).encode()}
    for name, data in initial.items():
        (root / name).write_bytes(data)
    inodes = {name: (root / name).stat().st_ino for name in initial}
    backup = apply(root, "config.yaml", ".env")
    assert all((root / name).stat().st_ino == inode for name, inode in inodes.items())
    assert (root / ".env").stat().st_mode & 0o777 == 0o600
    assert backup.stat().st_mode & 0o777 == 0o700
    rollback(root, backup)
    assert all((root / name).read_bytes() == data for name, data in initial.items())
    assert all((root / name).stat().st_ino == inode for name, inode in inodes.items())


def test_brain_conflicting_environment_is_rejected():
    original = json.dumps({"mcpServers": {"brain": {"headers": {"Authorization": "Bearer synthetic-token"}}}})
    with pytest.raises(ValueError, match="conflicts"):
        harden_brain(original, "BRAIN_MCP_AUTHORIZATION='Bearer different-token'\n")
