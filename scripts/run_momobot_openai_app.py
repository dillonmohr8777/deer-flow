"""Run the private app without forwarding provider credentials to Next.js.

Synchronize backend dependencies with ``uv sync --frozen --extra browser``
and build the frontend before running. The state directory must already hold
an authenticated configuration; this launcher never enables anonymous access.
Run ``prepare-config`` with the Gateway stopped to add a missing durable
run-event setting. Explicit owner settings are preserved without modification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import stat
import tempfile
from pathlib import Path


def _config_document(raw: bytes) -> dict:
    import yaml

    if len(raw) > 1024 * 1024:
        raise ValueError("private_config_invalid")
    try:
        document = yaml.safe_load(raw)
    except (UnicodeDecodeError, yaml.YAMLError):
        raise ValueError("private_config_invalid") from None
    if not isinstance(document, dict):
        raise ValueError("private_config_invalid")
    return document


def _journal_backend(document: dict) -> str | None:
    if "run_events" not in document:
        return None
    section = document["run_events"]
    if not isinstance(section, dict) or section.get("backend", "memory") not in (
        "memory",
        "db",
        "jsonl",
    ):
        raise ValueError("private_run_events_invalid")
    return section.get("backend", "memory")


def prepare_private_config(state: Path, *, expected_sha256: str | None = None) -> dict:
    """Append only the missing private SQL journal setting; never launch services.

    Stop the dedicated Gateway before invoking this operator command. Backups
    retain exact raw references/comments; no environment values are resolved.
    """
    state = state.absolute()
    config = state / "config.yaml"
    for path, directory in ((state, True), (config, False)):
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError("private_config_path_invalid")
        info = path.stat()
        expected_type = stat.S_ISDIR if directory else stat.S_ISREG
        if (
            not expected_type(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
        ):
            raise ValueError("private_config_path_invalid")
    raw = config.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and expected_sha256 != digest:
        raise ValueError("private_config_changed")
    document = _config_document(raw)
    backend = _journal_backend(document)
    if backend is not None:
        return {"changed": False, "backend": backend, "config_sha256": digest}
    database = document.get("database")
    if not isinstance(database, dict) or database.get("backend") != "sqlite":
        # The native event-store factory falls back to memory without SQL.
        # Reuse the owner's existing SQLite selection; never create/change it.
        raise ValueError("private_sqlite_backend_required")
    candidate = raw + b"\nrun_events:\n  backend: db\n"
    parsed = _config_document(candidate)
    if parsed.pop("run_events", None) != {"backend": "db"} or parsed != document:
        raise ValueError("private_config_append_changes_owner_settings")
    backup = state / f"config.yaml.before-run-events-db-{secrets.token_hex(8)}.bak"
    fd = os.open(
        backup,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(fd, "wb") as saved:
        saved.write(raw)
        saved.flush()
        os.fsync(saved.fileno())
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=state, prefix=".config-run-events-", delete=False
        ) as pending:
            temporary = Path(pending.name)
            os.chmod(temporary, 0o600)
            pending.write(candidate)
            pending.flush()
            os.fsync(pending.fileno())
        if config.read_bytes() != raw or config.is_symlink():
            raise ValueError("private_config_changed")
        os.replace(temporary, config)
        temporary = None
        directory = os.open(state, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {
        "changed": True,
        "backend": "db",
        "backup": str(backup),
        "config_sha256": hashlib.sha256(candidate).hexdigest(),
        "previous_config_sha256": digest,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=("gateway", "frontend", "prepare-config"))
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--expected-config-sha256")
    parser.add_argument("--gateway-port", type=int, default=8040)
    parser.add_argument("--frontend-port", type=int, default=3040)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    state = args.state_dir.resolve()
    if not (state / "config.yaml").is_file():
        parser.error("An authenticated config.yaml is required in --state-dir")
    if args.service == "prepare-config":
        try:
            result = prepare_private_config(
                args.state_dir, expected_sha256=args.expected_config_sha256
            )
        except (OSError, ValueError) as error:
            parser.error(
                str(error)
                if isinstance(error, ValueError)
                else "private_config_prepare_failed"
            )
        print(json.dumps(result))
        return
    if args.expected_config_sha256 is not None:
        parser.error("--expected-config-sha256 applies only to prepare-config")
    if not all(
        1024 <= port <= 65535 for port in (args.gateway_port, args.frontend_port)
    ):
        parser.error("Use unprivileged TCP ports")
    if args.gateway_port == args.frontend_port:
        parser.error("Gateway and frontend ports must be different")
    # Explicit allowlist prevents provider credentials leaking into the web
    # process or a future build; secrets are loaded only for the Gateway.
    env = {
        name: os.environ[name]
        for name in ("PATH", "HOME", "LANG", "TMPDIR")
        if name in os.environ
    }
    env.update(
        DEER_FLOW_ENV="production",
        DEER_FLOW_AUTH_COOKIE_PREFIX="momo_agent_",
        DEER_FLOW_INTERNAL_GATEWAY_BASE_URL=f"http://127.0.0.1:{args.gateway_port}",
    )
    if args.service == "gateway":
        from dotenv import dotenv_values

        try:
            document = _config_document((state / "config.yaml").read_bytes())
            backend = _journal_backend(document)
        except (OSError, ValueError):
            parser.error("Invalid private app run-event configuration")
        if backend is None:
            parser.error(
                "Private config needs run_events; run prepare-config with the Gateway stopped"
            )
        database = document.get("database")
        if backend == "db" and (
            not isinstance(database, dict)
            or database.get("backend") not in ("sqlite", "postgres")
        ):
            parser.error(
                "A db run-event journal requires the existing SQL database backend"
            )
        source = args.env_file or root / ".env.local"
        if not source.is_file() or source.stat().st_mode & 0o077 or source.is_symlink():
            parser.error("Use a regular private 0600 environment file")
        provider_settings = {
            "OPENAI_API_KEY",
            "MOMOBOT_OPENAI_AGENTS_ENABLED",
            "BROWSERBASE_API_KEY",
            "MOMOBOT_BROWSERBASE_ENABLED",
            "MOMOBOT_BROWSERBASE_MONTHLY_MINUTE_LIMIT",
            "MOMOBOT_WORKFLOWS_ENABLED",
            "MOMOBOT_STAGEHAND_EXTENSION_ID",
        }
        env.update(
            {
                key: value
                for key, value in dotenv_values(source).items()
                if key in provider_settings and value is not None
            }
        )
        env.update(
            DEER_FLOW_ENV="production",
            DEER_FLOW_HOME=str(state),
            DEER_FLOW_PROJECT_ROOT=str(root),
            DEER_FLOW_CONFIG_PATH=str(state / "config.yaml"),
            GATEWAY_HOST="127.0.0.1",
            GATEWAY_PORT=str(args.gateway_port),
        )
        # An isolated worktree may reuse a dependency environment whose editable
        # package links point at the preceding release. Select this source first.
        env["PYTHONPATH"] = os.pathsep.join(
            (str(root / "backend"), str(root / "backend/packages/harness"))
        )
        python = root / "backend/.venv/bin/python"
        os.chdir(root / "backend")
        os.execve(
            python,
            [
                str(python),
                "-m",
                "uvicorn",
                "app.gateway.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.gateway_port),
                "--log-level",
                "warning",
            ],
            env,
        )
    node = shutil.which("node")
    if node is None:
        parser.error("Node.js must be installed")
    os.chdir(root / "frontend")
    os.execve(
        node,
        [
            node,
            str(root / "frontend/node_modules/next/dist/bin/next"),
            "start",
            "--hostname",
            "127.0.0.1",
            "--port",
            str(args.frontend_port),
        ],
        env,
    )


if __name__ == "__main__":
    main()
