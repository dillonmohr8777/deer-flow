"""Read-only stdio JSON-RPC adapter for the fixed Brain HTTP MCP endpoint.

The transport never accepts a URL, header, or HTTP method from a client.
Only the explicitly listed read tools can reach the upstream service.
Snapshot mode reads an operator-installed cache and renderer without HTTP or rebuilds.
"""

import json
import runpy
from datetime import datetime
from pathlib import Path
import os
import sys
import urllib.request

UPSTREAM_URL = "http://host.docker.internal:8787/mcp"
ALLOWED_TOOLS = (
    "brain_now",
    "brain_client",
    "brain_open_items",
    "brain_search",
    "brain_systems",
)
MAX_INPUT_BYTES = 65536
MAX_RESPONSE_BYTES = 1048576
HTTP_TIMEOUT_SECONDS = 10
SAFE_INSTRUCTIONS = (
    "Read-only access to Dillon's live second brain. Call brain_now first and "
    "brain_client before client work. This adapter provides only the five read tools."
)


class ConfigurationError(Exception):
    """Configuration is invalid; never include its values in diagnostics."""


class UpstreamError(Exception):
    """The upstream response failed validation."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise UpstreamError()


class HTTPRequester:
    """Fixed destination, fixed headers and POST; redirects and proxies disabled."""

    def __init__(self, url, authorization):
        if url != UPSTREAM_URL:
            raise ConfigurationError()
        if (
            not isinstance(authorization, str)
            or not authorization.startswith("Bearer ")
            or not authorization[7:].strip()
            or len(authorization) > 4096
            or any(ord(c) < 32 or ord(c) > 126 for c in authorization)
        ):
            raise ConfigurationError()
        self._url = url
        self._authorization = authorization
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect()
        )

    def __call__(self, message):
        body = json.dumps(message, allow_nan=False).encode("utf-8")
        if len(body) > MAX_INPUT_BYTES:
            raise UpstreamError()
        request = urllib.request.Request(
            self._url,
            data=body,
            method="POST",
            headers={
                "Authorization": self._authorization,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        with self._opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise UpstreamError()
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise UpstreamError()
        return json.loads(raw, parse_constant=_invalid_constant)


def _invalid_constant(value):
    raise ValueError("Invalid JSON")


def _error(request_id, code, message):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _result(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


SNAPSHOT_TOOLS = tuple(name for name in ALLOWED_TOOLS if name != "brain_search")
SNAPSHOT_INSTRUCTIONS = (
    "Read-only saved Brain snapshot, not live state. Every response includes "
    "sourceObservedAt. Search, capture and refresh are unavailable."
)


class SnapshotRequester:
    """Use only pure renderers from the operator's unchanged private Brain module."""

    def __init__(self, directory):
        root = Path(directory)
        self.renderer = runpy.run_path(str(root / "brain.py"))
        self.data = json.loads(
            self._read(root / "brain.json"), parse_constant=_invalid_constant
        )
        self.now = self._read(root / "NOW.md")
        self.observed_at = self.data["generated_at"]
        if (
            not isinstance(self.observed_at, str)
            or datetime.fromisoformat(self.observed_at.replace("Z", "+00:00")).tzinfo
            is None
        ):
            raise ConfigurationError()

    @staticmethod
    def _read(path):
        with path.open("rb") as stream:
            raw = stream.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ConfigurationError()
        return raw.decode("utf-8")

    def __call__(self, message):
        method, params = message["method"], message["params"]
        if method == "initialize":
            result = {"protocolVersion": params["protocolVersion"]}
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        **tool,
                        "description": f"Read {tool['name']} from a saved Brain snapshot; sourceObservedAt={self.observed_at}.",
                    }
                    for tool in self.renderer["TOOLS"]
                    if tool["name"] in SNAPSHOT_TOOLS
                ]
            }
        elif method == "tools/call":
            name, args = params["name"], params["arguments"]
            if name == "brain_now":
                text = self.now
            elif name == "brain_client":
                hits = self.renderer["find_client"](self.data, args.get("name", ""))
                text = (
                    "\n\n".join(self.renderer["render_card"](client) for client in hits)
                    or "No client matches in this snapshot."
                )
            elif name == "brain_open_items":
                text = self.renderer["open_text"](self.data, args.get("client"))
            elif name == "brain_systems":
                text = self.renderer["systems_text"](self.data)
            else:
                raise UpstreamError()
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": f"Saved snapshot sourceObservedAt={self.observed_at}\n{text}",
                    }
                ],
                "_meta": {"sourceObservedAt": self.observed_at},
            }
        else:
            raise UpstreamError()
        return _result(1, result)


class Adapter:
    """The injected requester supports offline tests; it never receives credentials."""

    def __init__(
        self, requester, *, allowed_tools=ALLOWED_TOOLS, instructions=SAFE_INSTRUCTIONS
    ):
        self._requester = requester
        self._allowed_tools = allowed_tools
        self._instructions = instructions

    def _forward(self, request_id, method, params):
        try:
            # Brain is stateless. An internal id also handles downstream null ids.
            response = self._requester(
                {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
            )
            if (
                not isinstance(response, dict)
                or response.get("jsonrpc") != "2.0"
                or type(response.get("id")) is not int
                or response["id"] != 1
                or "error" in response
                or "result" not in response
            ):
                raise UpstreamError()
            result = response["result"]
            if not isinstance(result, dict):
                raise UpstreamError()
            if method == "initialize":
                version = result.get("protocolVersion")
                if not isinstance(version, str) or len(version) > 64:
                    raise UpstreamError()
                result = {
                    "protocolVersion": version,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "brain-readonly", "version": "1.0.0"},
                    "instructions": self._instructions,
                }
            elif method == "tools/list":
                tools = result.get("tools")
                if not isinstance(tools, list):
                    raise UpstreamError()
                selected = {}
                for tool in tools:
                    if not isinstance(tool, dict):
                        raise UpstreamError()
                    name = tool.get("name")
                    if name in self._allowed_tools:
                        if name in selected or not isinstance(
                            tool.get("inputSchema"), dict
                        ):
                            raise UpstreamError()
                        selected[name] = tool
                if set(selected) != set(self._allowed_tools):
                    raise UpstreamError()
                # Preserve tool schemas while exposing exactly the five permitted tools.
                result = {"tools": [selected[name] for name in self._allowed_tools]}
            elif method == "tools/call":
                if result.get("isError"):
                    result = {
                        "content": [{"type": "text", "text": "Brain read failed."}],
                        "isError": True,
                    }
                elif not isinstance(result.get("content"), list) or (
                    "isError" in result and type(result["isError"]) is not bool
                ):
                    raise UpstreamError()
            # Bound even fake/injected results before writing protocol output.
            if (
                len(json.dumps(result, allow_nan=False).encode("utf-8"))
                > MAX_RESPONSE_BYTES
            ):
                raise UpstreamError()
            return _result(request_id, result)
        except Exception:
            return _error(request_id, -32603, "Brain upstream unavailable.")

    def handle(self, message):
        if not isinstance(message, dict):
            return _error(None, -32600, "Invalid request.")
        request_id = message.get("id")
        if (
            message.get("jsonrpc") != "2.0"
            or (
                "id" in message
                and request_id is not None
                and type(request_id) not in (str, int)
            )
            or not isinstance(message.get("method"), str)
        ):
            return _error(None, -32600, "Invalid request.")
        method = message["method"]
        # Notifications never cause upstream calls, even if named tools/call.
        if "id" not in message:
            return None
        if method not in ("initialize", "ping", "tools/list", "tools/call"):
            return _error(request_id, -32601, "Method not permitted.")
        params = message.get("params", {})
        if not isinstance(params, dict):
            return _error(request_id, -32602, "Invalid parameters.")
        if method == "ping":
            return _result(request_id, {})
        if method == "tools/call":
            name = params.get("name")
            if not isinstance(name, str) or name not in self._allowed_tools:
                return _error(request_id, -32601, "Tool not permitted.")
            arguments = params.get("arguments", {})
            if not isinstance(arguments, dict) or set(params) - {"name", "arguments"}:
                return _error(request_id, -32602, "Invalid parameters.")
            forwarded = {"name": name, "arguments": arguments}
        elif method == "initialize":
            version = params.get("protocolVersion")
            if not isinstance(version, str) or not version or len(version) > 64:
                return _error(request_id, -32602, "Invalid parameters.")
            forwarded = {
                "protocolVersion": version,
                "capabilities": {},
                "clientInfo": {"name": "brain-readonly", "version": "1.0.0"},
            }
        else:
            if params:
                return _error(request_id, -32602, "Invalid parameters.")
            forwarded = {}
        return self._forward(request_id, method, forwarded)


def serve(adapter, input_stream, output_stream):
    """Newline-delimited MCP messages, with bounded reads and fixed errors."""
    while True:
        raw = input_stream.readline(MAX_INPUT_BYTES + 1)
        if not raw:
            return
        if len(raw) > MAX_INPUT_BYTES:
            # Drain only through this newline, with bounded memory.
            while raw and not raw.endswith(b"\n"):
                raw = input_stream.readline(MAX_INPUT_BYTES + 1)
            response = _error(None, -32600, "Request too large.")
        else:
            try:
                message = json.loads(raw, parse_constant=_invalid_constant)
            except (ValueError, UnicodeError, RecursionError):
                response = _error(None, -32700, "Parse error.")
            else:
                try:
                    response = adapter.handle(message)
                except Exception:
                    response = _error(None, -32603, "Request failed.")
        if response is not None:
            output_stream.write(json.dumps(response, allow_nan=False) + "\n")
            output_stream.flush()


def main():
    try:
        directory = os.environ.get("BRAIN_SNAPSHOT_DIR")
        if directory:
            adapter = Adapter(
                SnapshotRequester(directory),
                allowed_tools=SNAPSHOT_TOOLS,
                instructions=SNAPSHOT_INSTRUCTIONS,
            )
        else:
            requester = HTTPRequester(
                os.environ.get("BRAIN_MCP_UPSTREAM_URL"),
                os.environ.get("BRAIN_MCP_AUTHORIZATION"),
            )
            adapter = Adapter(requester)
        serve(adapter, sys.stdin.buffer, sys.stdout)
    except Exception:
        print("Brain read-only adapter stopped.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
