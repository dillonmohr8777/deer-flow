"""Bounded synthetic acceptance probe. Never executes returned tool calls."""

import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse

MODEL = "GLM-5.3-UNCENSORED-EXL3-3.0bpw"
IDENTIFIER = "001234567890"


def validate_tool_response(response):
    message = response["choices"][0]["message"]
    calls = message.get("tool_calls", [])
    if len(calls) != 1 or calls[0].get("type") != "function":
        raise ValueError("Expected exactly one function call")
    function = calls[0]["function"]
    arguments = json.loads(function["arguments"])
    if function["name"] != "lookup_order" or arguments != {"order_id": IDENTIFIER}:
        raise ValueError("Tool name or numeric-looking string argument was corrupted")


def request(base, key, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        base + path,
        data=data,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("Response exceeds probe limit")
    return json.loads(raw)


def main():
    base = os.environ.get("INFATOSHI_TABBY_BASE_URL", "").rstrip("/")
    key = os.environ.get("INFATOSHI_TABBY_API_KEY", "")
    parsed = urlparse(base)
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if not key or parsed.path != "/v1" or parsed.username or parsed.password:
        raise ValueError(
            "Provide the existing server key and /v1 base URL via environment"
        )
    if parsed.scheme != "https" and not (local and parsed.scheme == "http"):
        raise ValueError("Use HTTPS or a loopback SSH tunnel")
    models = request(base, key, "/models")
    if MODEL not in {model["id"] for model in models["data"]}:
        raise ValueError("Exact checkpoint ID missing; refusing substitution")
    response = request(
        base,
        key,
        "/chat/completions",
        {
            "model": MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": f"Call lookup_order with order_id exactly {IDENTIFIER}. Preserve every leading zero. Do not answer in prose.",
                }
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup_order",
                        "description": "Synthetic order lookup",
                        "parameters": {
                            "type": "object",
                            "properties": {"order_id": {"type": "string"}},
                            "required": ["order_id"],
                            "additionalProperties": False,
                        },
                    },
                }
            ],
            "tool_choice": "auto",
            "temperature": 0,
            "max_tokens": 2048,
            "stream": False,
        },
    )
    validate_tool_response(response)
    print(
        json.dumps(
            {
                "status": "passed",
                "model": MODEL,
                "numeric_string_preserved": True,
                "tool_executed": False,
                "requests": 2,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, IndexError, TypeError, urllib.error.URLError):
        print(
            '{"status":"failed","detail":"Check endpoint, exact model, authentication, and tool parser; secret-bearing error text suppressed"}'
        )
        raise SystemExit(1)
