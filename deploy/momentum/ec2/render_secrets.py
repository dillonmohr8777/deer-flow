"""Render SSM pairs for the host's atomic tmpfs env write; never log values."""

import asyncio
import contextlib
import io
import json
import re
import sys
from pathlib import Path

TOKEN_KEY = "OP_SERVICE_ACCOUNT_TOKEN"
HOST_ONLY = {TOKEN_KEY, "OP_CLIENTS_TOKEN"}  # read by host services only, never rendered into the app env
BROWSERBASE_REFS = {
    "BROWSERBASE_API_KEY": "op://ezfukkmm4vt7wqw6vp7l7eli3m/bjil477nt5c433kto6ys3qejw4/credential",
    "BROWSERBASE_PROJECT_ID": "op://ezfukkmm4vt7wqw6vp7l7eli3m/bjil477nt5c433kto6ys3qejw4/project_id",
}


async def resolve_browserbase(token, refs):
    # Legacy SSM-only starts require no 1Password package.
    from onepassword import Client

    client = await Client.authenticate(
        auth=token,
        integration_name="MomoBot EC2 Browserbase",
        integration_version="1.0.0",
    )
    return {key: await client.secrets.resolve(ref) for key, ref in refs.items()}


def validate_value(value, *, required=False):
    if (
        not isinstance(value, str)
        or any(c in value for c in "\n\r\0'")
        or (required and not value.strip())
    ):
        raise ValueError("invalid env value")


def render_env(parameters, settings, resolver=resolve_browserbase):
    if not isinstance(parameters, list) or not parameters:
        raise ValueError("no SSM parameters")
    pairs = []
    for row in parameters:
        if not isinstance(row, list) or len(row) != 2 or not isinstance(row[0], str):
            raise ValueError("invalid SSM row")
        key = row[0].rsplit("/", 1)[-1]
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError("invalid env key")
        validate_value(row[1])
        pairs.append((key, row[1]))
    tokens = [value for key, value in pairs if key == TOKEN_KEY]
    overrides = {}
    if tokens:
        if len(tokens) != 1:
            raise ValueError("duplicate service-account token")
        validate_value(tokens[0], required=True)
        # Discard SDK diagnostics; submitted values can appear in provider errors.
        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            overrides = asyncio.run(
                asyncio.wait_for(resolver(tokens[0], BROWSERBASE_REFS), timeout=30)
            )
        if (
            not isinstance(overrides, dict)
            or overrides.keys() != BROWSERBASE_REFS.keys()
        ):
            raise ValueError("invalid resolved keys")
        for value in overrides.values():
            validate_value(value, required=True)
    for line in settings.splitlines():
        match = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if match and (match[1] in HOST_ONLY or match[1] in overrides):
            raise ValueError("protected setting override")
    pairs = [
        (key, overrides.get(key, value)) for key, value in pairs if key not in HOST_ONLY
    ]
    existing = {key for key, _ in pairs}
    pairs.extend(
        (key, value) for key, value in overrides.items() if key not in existing
    )
    return "".join(f"{key}='{value}'\n" for key, value in pairs) + settings


def main():
    try:
        rendered = render_env(
            json.load(sys.stdin), Path(sys.argv[1]).read_text(encoding="utf-8")
        )
    except Exception:  # noqa: BLE001 - SDK exception text can contain submitted secrets.
        print("secret rendering failed", file=sys.stderr)
        return 1
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
