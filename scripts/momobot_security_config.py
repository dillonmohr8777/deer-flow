"""Narrow operator hardening with inode-preserving writes and exact rollback.

No container or provider calls. The companion runbook owns standby readback and
production approval. Credentials remain in a private environment file.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import yaml

MODELS = frozenset({"openrouter-gpt-6-luna", "openrouter-luna"})
ENV_NAME = "BRAIN_MCP_AUTHORIZATION"


def harden_models(text: str) -> str:
    """Change only the named model mappings; preserve the rest of the file."""
    current = yaml.safe_load(text)
    desired = copy.deepcopy(current)
    models = desired["models"]
    if {model["name"] for model in models} & MODELS != MODELS:
        raise ValueError("Required Luna models are missing")
    for model in models:
        if model["name"] in MODELS:
            model.setdefault("extra_body", {}).setdefault("provider", {}).update(
                zdr=True, data_collection="deny"
            )
    document = yaml.compose(text)
    sequence = next(value for key, value in document.value if key.value == "models")
    lines = text.splitlines(keepends=True)
    replacements = []
    for node, before, after in zip(
        sequence.value, current["models"], models, strict=True
    ):
        if before == after:
            continue
        # Replace one model block, keeping all unrelated text and comments.
        start = sum(map(len, lines[: node.start_mark.line]))
        end = sum(map(len, lines[: node.end_mark.line]))
        indent = " " * (node.start_mark.column - 2)
        dumped = yaml.safe_dump([after], sort_keys=False, width=240)
        replacements.append(
            (
                start,
                end,
                "".join(indent + line for line in dumped.splitlines(keepends=True)),
            )
        )
    for start, end, replacement in reversed(replacements):
        text = text[:start] + replacement + text[end:]
    if yaml.safe_load(text) != desired:
        raise ValueError("Model edit failed semantic preservation check")
    return text


def harden_brain(extensions: str, environment: str) -> tuple[str, str]:
    config = json.loads(extensions)
    brain = config["mcpServers"]["brain"]
    header = brain["headers"]["Authorization"]
    matches = re.findall(rf"(?m)^{ENV_NAME}=(.*)$", environment)
    if len(matches) > 1:
        raise ValueError("Duplicate Brain environment binding")
    existing = matches[0].strip().strip("\"'") if matches else None
    if header == f"${ENV_NAME}":
        header = existing
    if not isinstance(header, str) or not re.fullmatch(
        r"Bearer [A-Za-z0-9._~+/=-]+", header
    ):
        raise ValueError("Brain authorization binding is missing or invalid")
    if existing is not None and existing != header:
        raise ValueError(
            "Brain environment binding conflicts with configured credential"
        )
    if existing is None:
        environment = environment.rstrip("\n") + f"\n{ENV_NAME}='{header}'\n"
    brain["headers"]["Authorization"] = f"${ENV_NAME}"
    # No reviewed agent/client grant exists. Disabling is the fail-closed
    # containment; a future reviewed read-only binding is a separate action.
    brain["enabled"] = False
    return json.dumps(config, indent=2) + "\n", environment


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_in_place(path: Path, expected: bytes, replacement: bytes) -> None:
    """Fence bytes and retain the inode used by a single-file Docker mount."""
    import fcntl

    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    with os.fdopen(fd, "r+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        if handle.read() != expected:
            raise ValueError("Configuration changed since preparation")
        handle.seek(0)
        handle.write(replacement)
        handle.truncate()
        handle.flush()
        os.fsync(handle.fileno())


def candidates(
    root: Path, config_name: str, env_name: str
) -> dict[str, tuple[bytes, bytes]]:
    names = (config_name, "extensions_config.json", env_name)
    if any(Path(name).name != name for name in names):
        raise ValueError("Configuration filenames must be direct root children")
    original = {name: (root / name).read_bytes() for name in names}
    extensions, environment = harden_brain(
        original["extensions_config.json"].decode(), original[env_name].decode()
    )
    revised = {
        config_name: harden_models(original[config_name].decode()).encode(),
        "extensions_config.json": extensions.encode(),
        env_name: environment.encode(),
    }
    return {name: (original[name], revised[name]) for name in names}


def apply(root: Path, config_name: str, env_name: str) -> Path:
    changes = candidates(root, config_name, env_name)
    backup = root / "security-backups" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup.mkdir(parents=True, mode=0o700)
    os.chmod(backup.parent, 0o700)
    manifest = {}
    for name, (original, revised) in changes.items():
        with (backup / name).open("xb") as handle:
            os.chmod(handle.name, 0o600)
            handle.write(original)
        manifest[name] = {
            "before": digest(original),
            "after": digest(revised),
            "inode": (root / name).stat().st_ino,
        }
    (backup / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    os.chmod(backup / "manifest.json", 0o600)
    written = []
    try:
        # Set the protected environment binding before removing the inline copy.
        for name in (env_name, config_name, "extensions_config.json"):
            original, revised = changes[name]
            write_in_place(root / name, original, revised)
            written.append(name)
            if (root / name).stat().st_ino != manifest[name]["inode"]:
                raise ValueError("Bind-mounted file inode changed")
        os.chmod(root / env_name, 0o600)
    except Exception:
        for name in reversed(written):
            original, revised = changes[name]
            write_in_place(root / name, revised, original)
        raise
    return backup


def rollback(root: Path, backup: Path) -> None:
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    # Verify the complete transaction before touching any file.
    for name, entry in manifest.items():
        if (
            Path(name).name != name
            or digest((root / name).read_bytes()) != entry["after"]
            or digest((backup / name).read_bytes()) != entry["before"]
        ):
            raise ValueError("Rollback rejected: configuration or backup drift")
    for name in manifest:
        write_in_place(
            root / name, (root / name).read_bytes(), (backup / name).read_bytes()
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", type=Path)
    args = parser.parse_args()
    try:
        if args.rollback:
            rollback(args.root, args.rollback)
            print("Rollback restored exact bytes in place")
        elif args.apply:
            print(
                "Protected rollback directory:", apply(args.root, args.config, args.env)
            )
        else:
            changes = candidates(args.root, args.config, args.env)
            print(
                json.dumps(
                    {
                        "mode": "plan",
                        "files_changed": [
                            name
                            for name, (before, after) in changes.items()
                            if before != after
                        ],
                        "brain_enabled_after": False,
                        "luna_privacy_after": "zdr=true,data_collection=deny",
                    }
                )
            )
        return 0
    except Exception as error:
        # Underlying YAML/JSON exceptions can contain private field values.
        print(
            f"Hardening stopped ({type(error).__name__}); no credential details emitted"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
