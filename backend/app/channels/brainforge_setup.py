"""Offline preparation and read-only preflight for the existing Slack workflow.

No credentials, network, builder execution, live config writes or activation.
Prepared source hashes are candidate pins, never an acceptance/freshness claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import uuid
from pathlib import Path
from typing import Any

import yaml

from app.channels.brainforge_intake import _CREDENTIAL, _ID, ScopePolicy, _valid, _valid_route
from app.channels.brainforge_workflow import BRIEF_MODULES, SOURCE_FILES, BrainForgeBriefWorkflow

BINDINGS = frozenset({"team_id", "bot_user_id", "allowed_users", "channel_clients", "owner_user_id", "connection_owner_id"})
CONFIG_KEYS = BINDINGS | {"enabled", "require_connection", "ledger_path", "workflow", "source_pin_status"}
WORKFLOW_KEYS = {"brief_source", "canonical_root", "artifact_root", "brief_source_hashes", "source_hashes"}
UNVERIFIED = [
    "source_acceptance_and_freshness",
    "live_owner_binding",
    "encrypted_connection_token",
    "channel_connections_enabled",
    "persistent_connection_database",
    "socket_transport",
    "persistent_host",
    "authorized_canary",
]
ENV_REFERENCES = ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "CHANNEL_CONNECTIONS_ENCRYPTION_KEY")


class SetupError(ValueError):
    """Only fixed reason codes may be exposed by the CLI."""


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if not isinstance(key, str) or key in result:
            raise SetupError("duplicate_or_invalid_key")
        result[key] = value
    return result


class _UniqueSafeLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        return _pairs((self.construct_object(key, deep=deep), self.construct_object(value, deep=deep)) for key, value in node.value)

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise SetupError("yaml_alias_not_allowed")
        return super().compose_node(parent, index)


def _path(value: Any) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip() or ".." in Path(value).parts:
        raise SetupError("invalid_path")
    path = Path(value).absolute()
    if any(candidate.is_symlink() for candidate in (path, *path.parents)):
        raise SetupError("symlink_path")
    return path


def _outside(path: Path, roots: tuple[Path, ...]) -> None:
    if any(path.is_relative_to(root) or root.is_relative_to(path) for root in roots):
        raise SetupError("overlapping_source_or_storage_paths")


def _private(path: Path, *, directory: bool) -> None:
    if path.exists():
        if (not path.is_dir() if directory else not path.is_file()) or (os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077):
            raise SetupError("private_path_required")


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    if not isinstance(value, dict):
        raise SetupError("object_required")
    return value


def _bindings(raw: dict) -> dict:
    if not isinstance(raw, dict) or set(raw) - BINDINGS:
        raise SetupError("invalid_binding_fields")
    result = {"team_id": "", "bot_user_id": "", "allowed_users": [], "channel_clients": {}, "owner_user_id": "", "connection_owner_id": "", **raw}
    if _CREDENTIAL.search(json.dumps(result)):
        raise SetupError("credential_shaped_binding_rejected")
    for key in ("team_id", "bot_user_id", "owner_user_id"):
        if not isinstance(result[key], str) or (result[key] and not _valid(result[key], _ID)):
            raise SetupError("invalid_binding_values")
    users, routes, owner = result["allowed_users"], result["channel_clients"], result["connection_owner_id"]
    if not isinstance(users, list) or any(not _valid(user, _ID) for user in users) or len(users) != len(set(users)):
        raise SetupError("invalid_binding_values")
    if not isinstance(routes, dict) or any(not _valid(channel, _ID) or not _valid_route(client) for channel, client in routes.items()):
        raise SetupError("invalid_binding_values")
    if not isinstance(owner, str) or (owner and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", owner)):
        raise SetupError("invalid_binding_values")
    return result


def _source_pins(root: Path, names: frozenset[str]) -> dict[str, str]:
    return {name: hashlib.sha256(_path(root / name).read_bytes()).hexdigest() for name in sorted(names)}


def _validate_local(config: dict, fragment: Path) -> dict:
    if not isinstance(config, dict) or set(config) != CONFIG_KEYS or config["enabled"] is not False or config["require_connection"] is not True or config["source_pin_status"] != "candidate_unreviewed":
        raise SetupError("disabled_candidate_fragment_required")
    bindings = _bindings({key: config[key] for key in BINDINGS})
    workflow = config["workflow"]
    if not isinstance(workflow, dict) or set(workflow) - {"project"} != WORKFLOW_KEYS:
        raise SetupError("invalid_workflow_fields")
    source, canonical, artifact, ledger = (_path(value) for value in (workflow["brief_source"], workflow["canonical_root"], workflow["artifact_root"], config["ledger_path"]))
    roots = (source, canonical)
    for path in (artifact, ledger.parent, fragment):
        _outside(path, roots)
    _outside(artifact, (ledger, fragment))
    if ledger == fragment:
        raise SetupError("overlapping_source_or_storage_paths")
    for directory in (artifact, ledger.parent, fragment.parent):
        _private(directory, directory=True)
    _private(ledger, directory=False)
    _private(fragment, directory=False)
    # Also validate ancestor links of registry/queue files before reusing the
    # workflow's exact pin validation. Construction never launches its builder.
    _source_pins(source, BRIEF_MODULES)
    _source_pins(canonical, SOURCE_FILES)
    try:
        BrainForgeBriefWorkflow(workflow)
    except (ValueError, TypeError, KeyError):
        raise SetupError("source_pins_invalid_or_drifted") from None
    registry = _json(canonical / "registry/clients.json")
    _json(canonical / "queue/work-items.json")
    clients = registry.get("clients")
    if not isinstance(clients, list) or any(not isinstance(client, dict) or not _valid_route(client.get("id")) for client in clients):
        raise SetupError("invalid_registry")
    ids = [client["id"] for client in clients]
    if len(ids) != len(set(ids)):
        raise SetupError("ambiguous_registry")
    active = {client["id"] for client in clients if client.get("status") == "active"}
    missing = sorted(key for key in BINDINGS if not bindings[key])
    policy = ScopePolicy(bindings["team_id"], frozenset(bindings["allowed_users"]), bindings["channel_clients"], bindings["bot_user_id"])
    routes_valid = all(route == "__owner__" or route in active for route in policy.channel_clients.values())
    owner_valid = bindings["owner_user_id"] in policy.allowed_users
    ready = not missing and policy.valid and routes_valid and owner_valid
    return {
        "status": "local_candidate_ready" if ready else "local_configuration_incomplete",
        "local_configuration_ready": ready,
        "enabled": False,
        "pins": "candidate_unreviewed",
        "source_hashes_match": True,
        "scope_valid": policy.valid,
        "routes_resolve_active": routes_valid,
        "owner_allowed": owner_valid,
        "missing_binding_fields": missing,
        "live_readiness": "unverified",
        "unverified": UNVERIFIED,
        "credentials_read": False,
        "environment_presence": {name: name in os.environ for name in ENV_REFERENCES},
        "network_calls": 0,
    }


def prepare(*, brief_source: str, canonical_root: str, storage_root: str, out: str, bindings: str | None = None) -> dict:
    source, canonical, storage, output = map(_path, (brief_source, canonical_root, storage_root, out))
    for path in (storage, output):
        _outside(path, (source, canonical))
    if output.exists():
        raise SetupError("output_already_exists")
    _private(storage, directory=True)
    _private(output.parent, directory=True)
    scope = _bindings(_json(_path(bindings)) if bindings else {})
    config = {
        "enabled": False,
        "require_connection": True,
        "source_pin_status": "candidate_unreviewed",
        **scope,
        "ledger_path": str(storage / "transport.sqlite3"),
        "workflow": {
            "brief_source": str(source),
            "canonical_root": str(canonical),
            "artifact_root": str(storage / f"artifacts-{uuid.uuid4().hex}"),
            "brief_source_hashes": _source_pins(source, BRIEF_MODULES),
            "source_hashes": _source_pins(canonical, SOURCE_FILES),
        },
    }
    report = _validate_local(config, output)
    # All validation precedes any output creation. Existing private parents are
    # never chmodded; exclusive creation cannot overwrite a running config.
    storage.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    raw = "# Candidate source pins only; review required. No live configuration was changed.\n" + yaml.safe_dump({"channels": {"slack": {"brain_forge": config}}}, sort_keys=False)
    with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600), "w", encoding="utf-8") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {**report, "prepared": True}


def check(fragment: str) -> dict:
    path = _path(fragment)
    _private(path, directory=False)
    document = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueSafeLoader)
    if not isinstance(document, dict) or set(document) != {"channels"} or not isinstance(document["channels"], dict) or set(document["channels"]) != {"slack"}:
        raise SetupError("disabled_candidate_fragment_required")
    slack = document["channels"]["slack"]
    if not isinstance(slack, dict) or set(slack) != {"brain_forge"}:
        raise SetupError("disabled_candidate_fragment_required")
    return _validate_local(slack["brain_forge"], path)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        print(json.dumps({"status": "error", "reason": "arguments_invalid", "local_configuration_ready": False}))
        raise SystemExit(2)


def main(argv=None) -> int:
    parser = _Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    for name in ("brief-source", "canonical-root", "storage-root", "out"):
        prepare_parser.add_argument(f"--{name}", required=True)
    prepare_parser.add_argument("--bindings")
    commands.add_parser("check").add_argument("--fragment", required=True)
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    try:
        report = prepare(**args) if command == "prepare" else check(**args)
        print(json.dumps(report, sort_keys=True))
        return 0 if report["local_configuration_ready"] else 1
    except Exception as error:
        reason = str(error) if isinstance(error, SetupError) else "configuration_rejected"
        print(json.dumps({"status": "error", "reason": reason, "local_configuration_ready": False}))
        return 2
