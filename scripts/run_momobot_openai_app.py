"""Run the private app without forwarding provider credentials to Next.js.

Synchronize backend dependencies with ``uv sync --frozen --extra browser``
and build the frontend before running. The state directory must already hold
an authenticated configuration; this launcher never enables anonymous access.
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=("gateway", "frontend"))
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--gateway-port", type=int, default=8040)
    parser.add_argument("--frontend-port", type=int, default=3040)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    state = args.state_dir.resolve()
    if not (state / "config.yaml").is_file():
        parser.error("An authenticated config.yaml is required in --state-dir")
    if not all(1024 <= port <= 65535 for port in (args.gateway_port, args.frontend_port)):
        parser.error("Use unprivileged TCP ports")
    if args.gateway_port == args.frontend_port:
        parser.error("Gateway and frontend ports must be different")
    # Explicit allowlist prevents provider credentials leaking into the web
    # process or a future build; secrets are loaded only for the Gateway.
    env = {name: os.environ[name] for name in ("PATH", "HOME", "LANG", "TMPDIR") if name in os.environ}
    env.update(DEER_FLOW_ENV="production", DEER_FLOW_AUTH_COOKIE_PREFIX="momo_agent_", DEER_FLOW_INTERNAL_GATEWAY_BASE_URL=f"http://127.0.0.1:{args.gateway_port}")
    if args.service == "gateway":
        from dotenv import dotenv_values

        source = args.env_file or root / ".env.local"
        if not source.is_file() or source.stat().st_mode & 0o077 or source.is_symlink():
            parser.error("Use a regular private 0600 environment file")
        provider_settings = {"OPENAI_API_KEY", "MOMOBOT_OPENAI_AGENTS_ENABLED", "BROWSERBASE_API_KEY", "MOMOBOT_BROWSERBASE_ENABLED", "MOMOBOT_BROWSERBASE_MONTHLY_MINUTE_LIMIT"}
        env.update({key: value for key, value in dotenv_values(source).items() if key in provider_settings and value is not None})
        env.update(DEER_FLOW_ENV="production", DEER_FLOW_HOME=str(state), DEER_FLOW_PROJECT_ROOT=str(root), DEER_FLOW_CONFIG_PATH=str(state / "config.yaml"), GATEWAY_HOST="127.0.0.1", GATEWAY_PORT=str(args.gateway_port))
        python = root / "backend/.venv/bin/python"
        os.chdir(root / "backend")
        os.execve(python, [str(python), "-m", "uvicorn", "app.gateway.app:app", "--host", "127.0.0.1", "--port", str(args.gateway_port), "--log-level", "warning"], env)
    node = shutil.which("node")
    if node is None:
        parser.error("Node.js must be installed")
    os.chdir(root / "frontend")
    os.execve(node, [node, str(root / "frontend/node_modules/next/dist/bin/next"), "start", "--hostname", "127.0.0.1", "--port", str(args.frontend_port)], env)


if __name__ == "__main__":
    main()
