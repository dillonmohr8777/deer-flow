"""Read-only stdio JSON-RPC adapter for the fixed Brain HTTP MCP endpoint.

The transport never accepts a URL, header, or HTTP method from a client.
Only the explicitly listed read tools can reach the upstream service.
Snapshot mode reads an operator-installed cache and renderer without HTTP or rebuilds.
"""

import hashlib
import json
import math
import os
import re
import stat
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

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
SAFE_INSTRUCTIONS = "Read-only access to Dillon's live second brain. Call brain_now first and brain_client before client work. This adapter provides only the five read tools."


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
SNAPSHOT_INSTRUCTIONS = "Read-only saved Brain snapshot, not live state. Every response includes sourceObservedAt. Search, capture and refresh are unavailable."
MAX_SNAPSHOT_METADATA_BYTES = 4096
SNAPSHOT_FILES = ("brain.json", "NOW.md")


def snapshot_directory(directory):
    root = Path(os.path.abspath(directory))
    if root.resolve(strict=True) != root or not root.is_dir():
        raise ConfigurationError()
    return root


def read_snapshot_file(path, limit=MAX_RESPONSE_BYTES):
    """Read only bounded, stable regular files, never links or special files."""
    snapshot_directory(path.parent)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ConfigurationError()
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_BINARY", 0)
    )
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or opened.st_size > limit:
            raise ConfigurationError()
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())

    def signature(value):
        return (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
            value.st_nlink,
        )

    if len(raw) > limit or not signature(before) == signature(opened) == signature(
        after
    ) == signature(path.lstat()):
        raise ConfigurationError()
    return raw


def _unique_snapshot_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConfigurationError()
        result[key] = value
    return result


def _finite_snapshot_float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ConfigurationError()
    return parsed


def _snapshot_json(raw):
    return json.loads(
        raw.decode("utf-8"),
        parse_constant=_invalid_constant,
        parse_float=_finite_snapshot_float,
        object_pairs_hook=_unique_snapshot_object,
    )


def snapshot_json(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def snapshot_timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ConfigurationError()
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if observed.utcoffset() is None:
            raise ValueError()
    except ValueError:
        raise ConfigurationError() from None
    return observed


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _is_sha256(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def load_snapshot_renderer(root, expected_hash=None):
    raw = read_snapshot_file(root / "brain.py")
    digest = _sha256(raw)
    if expected_hash is not None and (
        not _is_sha256(expected_hash) or digest != expected_hash
    ):
        raise ConfigurationError()
    # Only this operator-installed, pinned root module is code; payloads are JSON/text.
    renderer = {
        "__name__": "__brain_snapshot_renderer__",
        "__file__": str(root / "brain.py"),
    }
    exec(compile(raw, str(root / "brain.py"), "exec"), renderer)
    if not isinstance(renderer.get("TOOLS"), list) or any(
        not callable(renderer.get(name))
        for name in (
            "render_now",
            "find_client",
            "render_card",
            "open_text",
            "systems_text",
        )
    ):
        raise ConfigurationError()
    return renderer, digest


def load_snapshot_pair(root, renderer):
    payloads = {name: read_snapshot_file(root / name) for name in SNAPSHOT_FILES}
    data = _snapshot_json(payloads["brain.json"])
    required = {
        "clients": dict,
        "open_items": list,
        "loop_cards": list,
        "systems": dict,
    }
    if not isinstance(data, dict) or any(
        not isinstance(data.get(key), kind) for key, kind in required.items()
    ):
        raise ConfigurationError()
    observed_at = data.get("generated_at")
    snapshot_timestamp(observed_at)
    now = payloads["NOW.md"].decode("utf-8")
    if renderer["render_now"](data) != now:
        raise ConfigurationError()
    return (data, now, observed_at), payloads


def read_current_pointer(root):
    snapshot_directory(root)
    try:
        return read_snapshot_file(root / "current.json", MAX_SNAPSHOT_METADATA_BYTES)
    except FileNotFoundError:
        return None


def parse_current_pointer(raw):
    pointer = _snapshot_json(raw)
    if (
        not isinstance(pointer, dict)
        or set(pointer) != {"schemaVersion", "generation"}
        or type(pointer["schemaVersion"]) is not int
        or pointer["schemaVersion"] != 1
        or not _is_sha256(pointer["generation"])
    ):
        raise ConfigurationError()
    return pointer["generation"]


def generation_id(metadata):
    return _sha256(snapshot_json(metadata))


def load_generation(root, generation, renderer, renderer_hash):
    if not _is_sha256(generation):
        raise ConfigurationError()
    directory = snapshot_directory(root / "generations" / generation)
    manifest = _snapshot_json(
        read_snapshot_file(directory / "manifest.json", MAX_SNAPSHOT_METADATA_BYTES)
    )
    if not isinstance(manifest, dict) or set(manifest) != {
        "schemaVersion",
        "generation",
        "sourceObservedAt",
        "rendererSha256",
        "files",
    }:
        raise ConfigurationError()
    metadata = {key: value for key, value in manifest.items() if key != "generation"}
    if (
        type(manifest["schemaVersion"]) is not int
        or manifest["schemaVersion"] != 1
        or manifest["generation"] != generation
        or generation_id(metadata) != generation
        or manifest["rendererSha256"] != renderer_hash
        or not isinstance(manifest["files"], dict)
        or set(manifest["files"]) != set(SNAPSHOT_FILES)
    ):
        raise ConfigurationError()
    state, payloads = load_snapshot_pair(directory, renderer)
    if state[2] != manifest["sourceObservedAt"] or any(
        _sha256(raw) != manifest["files"][name] for name, raw in payloads.items()
    ):
        raise ConfigurationError()
    return (*state, generation)


class SnapshotRequester:
    """Use only pure renderers from the operator's unchanged private Brain module."""

    def __init__(self, directory):
        self.root = snapshot_directory(directory)
        self.renderer, self._renderer_hash = load_snapshot_renderer(self.root)
        self._pointer = self._state = None
        self._generation_mode = False
        self._refresh()

    def _refresh(self):
        if _sha256(read_snapshot_file(self.root / "brain.py")) != self._renderer_hash:
            raise ConfigurationError()
        pointer = read_current_pointer(self.root)
        if pointer is None:
            if self._generation_mode:
                raise ConfigurationError()
            if self._state is None:
                state, _ = load_snapshot_pair(self.root, self.renderer)
                if read_current_pointer(self.root) is not None:
                    raise ConfigurationError()
                self._state = (*state, "legacy")
            return self._state
        self._generation_mode = True
        generation = parse_current_pointer(pointer)
        # Root can alter even private files; revalidate unchanged selections too.
        candidate = load_generation(
            self.root, generation, self.renderer, self._renderer_hash
        )
        if read_current_pointer(self.root) != pointer:
            raise ConfigurationError()
        if pointer != self._pointer:
            # Swap the whole validated generation; failures never select cached old data.
            self._state, self._pointer = candidate, pointer
        return self._state

    def __call__(self, message):
        method, params = message["method"], message["params"]
        if method in ("tools/list", "tools/call"):
            data, now, observed_at, generation = self._refresh()
            metadata = {"sourceObservedAt": observed_at, "generation": generation}
        if method == "initialize":
            result = {"protocolVersion": params["protocolVersion"]}
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        **tool,
                        "description": f"Read {tool['name']} from a saved Brain snapshot; sourceObservedAt={observed_at}; generation={generation}.",
                        "_meta": metadata,
                    }
                    for tool in self.renderer["TOOLS"]
                    if tool["name"] in SNAPSHOT_TOOLS
                ]
            }
        elif method == "tools/call":
            name, args = params["name"], params["arguments"]
            if name == "brain_now":
                text = now
            elif name == "brain_client":
                hits = self.renderer["find_client"](data, args.get("name", ""))
                text = (
                    "\n\n".join(self.renderer["render_card"](client) for client in hits)
                    or "No client matches in this snapshot."
                )
            elif name == "brain_open_items":
                text = self.renderer["open_text"](data, args.get("client"))
            elif name == "brain_systems":
                text = self.renderer["systems_text"](data)
            else:
                raise UpstreamError()
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": f"Saved snapshot sourceObservedAt={observed_at}\n{text}",
                    }
                ],
                "_meta": metadata,
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
