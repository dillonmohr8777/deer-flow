#!/usr/bin/env python3
"""Owner-scoped CLI for MomoBot's existing workflow API, with no local scheduler."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import http.cookiejar
import ipaddress
import json
import os
import re
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

FRAMEWORKS = ("langgraph", "crewai", "mastra", "deepagents", "agno", "agentkit")
MAX_JSON = 262144
ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
COOKIE_NAMES = {
    "momo_agent_access_token",
    "momo_agent_deerflow_session_persistent",
    "csrf_token",
}
TERMINAL = {"completed", "failed", "cancelled"}
AUTH = "/api/v1/auth"


class WorkbenchError(RuntimeError):
    pass


def server_origin(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
        loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if not loopback and parsed.hostname:
            try:
                loopback = ipaddress.ip_address(parsed.hostname).is_loopback
            except ValueError:
                pass
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not parsed.hostname
            or parsed.hostname.endswith(".")
            or (port is not None and not 1 <= port <= 65535)
        ):
            raise ValueError
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
            raise ValueError
        if parsed.path not in {"", "/", "/workspace/openai", "/workspace/workflows"}:
            raise ValueError
        return f"{parsed.scheme}://{parsed.netloc}"
    except (TypeError, ValueError):
        raise WorkbenchError("invalid_server_endpoint") from None


def read_private(path: Path, limit=MAX_JSON) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        raise WorkbenchError("private_file_unavailable") from None
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
            or info.st_size > limit
        ):
            raise WorkbenchError("private_file_permissions_invalid")
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise WorkbenchError("private_file_too_large")
        return data


def private_directory(path: Path):
    if not path.exists() and not path.is_symlink():
        path.mkdir(parents=True, mode=0o700)
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) & 0o077
    ):
        raise WorkbenchError("private_directory_permissions_invalid")


def write_private(path: Path, data: bytes, *, replace=False):
    private_directory(path.parent)
    if path.exists() or path.is_symlink():
        read_private(path)
        if not replace:
            raise WorkbenchError("output_exists")
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            # O_EXCL semantics survive concurrent creation of an artifact target.
            os.link(temporary, path)
            temporary.unlink()
    finally:
        if temporary.exists():
            temporary.unlink()


def configured_server(explicit: str | None = None) -> str:
    value = explicit or os.environ.get("MOMO_WORKBENCH_SERVER")
    if not value:
        config = Path.home() / "Library/Application Support/MomoBot/connection.json"
        try:
            value = json.loads(read_private(config)).get("endpoint")
        except (WorkbenchError, ValueError):
            raise WorkbenchError("server_not_configured_use_server") from None
    return server_origin(value)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise WorkbenchError("redirect_rejected")


class WorkbenchClient:
    def __init__(self, server: str, state: Path, *, opener=None):
        self.server = server_origin(server)
        self.state = state
        self.auth_file = state / "auth.json"
        self.user_id = None
        self.scope = None
        self.jar = http.cookiejar.CookieJar(
            policy=http.cookiejar.DefaultCookiePolicy(strict_domain=True)
        )
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            NoRedirect(),
            urllib.request.HTTPCookieProcessor(self.jar),
        )
        if self.auth_file.exists() or self.auth_file.is_symlink():
            try:
                auth = json.loads(read_private(self.auth_file))
                if (
                    auth.get("server") != self.server
                    or not ID.fullmatch(auth.get("user_id", ""))
                    or not re.fullmatch(r"[a-f0-9]{64}", auth.get("scope", ""))
                ):
                    raise WorkbenchError("saved_owner_scope_invalid")
                self.user_id, self.scope = auth["user_id"], auth["scope"]
                for saved in auth.get("cookies", []):
                    if (
                        saved.get("name") not in COOKIE_NAMES
                        or not isinstance(saved.get("value"), str)
                        or not saved["value"]
                        or len(saved["value"]) > 8192
                    ):
                        raise WorkbenchError("saved_session_invalid")
                    if (
                        saved.get("domain", "").lstrip(".")
                        != urllib.parse.urlsplit(self.server).hostname
                        or saved.get("path") != "/"
                    ):
                        raise WorkbenchError("saved_session_origin_mismatch")
                    self.jar.set_cookie(
                        http.cookiejar.Cookie(
                            version=0,
                            port=None,
                            port_specified=False,
                            name=saved["name"],
                            value=saved["value"],
                            domain=saved["domain"],
                            domain_specified=False,
                            domain_initial_dot=False,
                            path="/",
                            path_specified=True,
                            secure=bool(saved.get("secure")),
                            expires=saved.get("expires"),
                            discard=saved.get("expires") is None,
                            comment=None,
                            comment_url=None,
                            rest={},
                        )
                    )
            except (KeyError, TypeError, ValueError):
                raise WorkbenchError("saved_session_invalid") from None

    def request(
        self,
        method: str,
        path: str,
        body=None,
        *,
        headers=None,
        form=False,
        binary=False,
    ):
        if not path.startswith("/api/") and path != "/health":
            raise WorkbenchError("api_path_rejected")
        extra = {
            "Accept": "application/json",
            "User-Agent": "MomoWorkbench/0.1",
            **(headers or {}),
        }
        if self.scope and path.startswith("/api/workflows/"):
            extra["X-Expected-Workflow-Scope"] = self.scope
        if method != "GET":
            extra["Origin"] = self.server
            csrf = next(
                (
                    cookie.value
                    for cookie in self.jar
                    if cookie.name == "csrf_token"
                    and cookie.domain.lstrip(".")
                    == urllib.parse.urlsplit(self.server).hostname
                ),
                None,
            )
            if csrf:
                extra["X-CSRF-Token"] = csrf
        data = None
        if body is not None:
            data = (
                urllib.parse.urlencode(body).encode()
                if form
                else json.dumps(body, allow_nan=False, separators=(",", ":")).encode()
            )
            if len(data) > MAX_JSON:
                raise WorkbenchError("input_too_large")
            extra["Content-Type"] = (
                "application/x-www-form-urlencoded" if form else "application/json"
            )
        request = urllib.request.Request(
            self.server + path, data=data, headers=extra, method=method
        )
        response_limit = 1024 * 1024 if path == "/api/workflows/catalog" else MAX_JSON
        try:
            with self.opener.open(request, timeout=30) as response:
                target = urllib.parse.urlsplit(response.geturl())
                if f"{target.scheme}://{target.netloc}" != self.server:
                    raise WorkbenchError("response_origin_mismatch")
                raw = response.read(response_limit + 1)
                if len(raw) > response_limit:
                    raise WorkbenchError("response_too_large")
                if binary:
                    return raw
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise WorkbenchError("invalid_response_object")
                return result
        except urllib.error.HTTPError as error:
            # Never print server-controlled bodies, credentials, MFA challenges or prompts.
            raise WorkbenchError(f"http_{error.code}") from None
        except (
            urllib.error.URLError,
            TimeoutError,
            ValueError,
            OSError,
            RecursionError,
        ):
            raise WorkbenchError("transport_or_response_failed") from None

    def authorize(self, *, fresh=False):
        identity = self.request("GET", AUTH + "/me")
        actor = str(identity.get("id", ""))
        if not ID.fullmatch(actor) or (
            not fresh and self.user_id and actor != self.user_id
        ):
            raise WorkbenchError("owner_identity_changed")
        status = self.request(
            "GET", "/api/workflows/status", headers={"X-Expected-User-Id": actor}
        )
        scope = status.get("owner_scope", "")
        if not re.fullmatch(r"[a-f0-9]{64}", scope) or (
            not fresh and self.scope and scope != self.scope
        ):
            raise WorkbenchError("owner_scope_changed_login_again")
        self.user_id, self.scope = actor, scope
        return status

    def doctor(self):
        try:
            gateway = self.request("GET", "/health")
        except WorkbenchError as error:
            if str(error) != "http_404":
                raise
            # The installed frontend proxies /api/*, not the direct gateway
            # /health route. Its existing public auth probe reaches the same
            # configured gateway without a session or another exposed route.
            setup = self.request("GET", AUTH + "/setup-status")
            if type(setup.get("needs_setup")) is not bool:
                raise WorkbenchError("invalid_gateway_probe")
            gateway = {
                "reachable": True,
                "auth_configured": not setup["needs_setup"],
                "probe": "auth_setup_status",
            }
        result = {
            "server": self.server,
            "gateway": gateway,
            "session_saved": self.auth_file.exists(),
            "automatic_execution": False,
        }
        if self.user_id:
            result["workflows"] = self.authorize()
        else:
            result["authentication"] = "sign_in_required"
        return result

    def save_session(self):
        cookies = []
        for cookie in self.jar:
            if (
                cookie.name in COOKIE_NAMES
                and cookie.domain.lstrip(".")
                == urllib.parse.urlsplit(self.server).hostname
                and cookie.path == "/"
            ):
                cookies.append(
                    {
                        "name": cookie.name,
                        "value": cookie.value,
                        "domain": cookie.domain,
                        "path": cookie.path,
                        "secure": cookie.secure,
                        "expires": cookie.expires,
                    }
                )
        if not any(cookie["name"] == "momo_agent_access_token" for cookie in cookies):
            raise WorkbenchError("private_app_session_cookie_missing")
        content = json.dumps(
            {
                "server": self.server,
                "user_id": self.user_id,
                "scope": self.scope,
                "cookies": cookies,
            },
            allow_nan=False,
        ).encode()
        write_private(self.auth_file, content, replace=True)

    def login(self, email: str, password: str, mfa_prompt=getpass.getpass):
        result = self.request(
            "POST",
            AUTH + "/login/local",
            {"username": email, "password": password, "remember_me": "true"},
            form=True,
        )
        if result.get("mfa_required") is True:
            challenge = result.get("challenge")
            if not isinstance(challenge, str) or not challenge:
                raise WorkbenchError("invalid_mfa_challenge")
            code = mfa_prompt("MFA code from your authenticator: ")
            if not re.fullmatch(r"[0-9]{6}", code):
                raise WorkbenchError("invalid_mfa_code")
            self.request(
                "POST",
                AUTH + "/login/mfa",
                {"challenge": challenge, "code": code, "remember_me": True},
            )
        self.authorize(fresh=True)
        self.save_session()
        return {"authenticated": True, "owner_id": self.user_id}

    def catalog(self):
        self.authorize()
        return self.request("GET", "/api/workflows/catalog")

    def run(
        self, workflow: str, inputs: dict, framework: str, *, key: str | None = None
    ):
        self.authorize()
        if (
            not ID.fullmatch(workflow)
            or framework not in FRAMEWORKS
            or not isinstance(inputs, dict)
        ):
            raise WorkbenchError("invalid_run_request")
        key = key or "cli_" + uuid.uuid4().hex
        if not ID.fullmatch(key):
            raise WorkbenchError("invalid_idempotency_key")
        payload = {"workflow_id": workflow, "inputs": inputs, "framework": framework}
        fingerprint = hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, allow_nan=False, separators=(",", ":")
            ).encode()
        ).hexdigest()
        self.receipt(
            {
                "event": "admission_requested",
                "idempotency_key": key,
                "request_sha256": fingerprint,
                "owner_scope": self.scope,
            }
        )
        try:
            result = self.request(
                "POST", "/api/workflows/runs", payload, headers={"Idempotency-Key": key}
            )
        except WorkbenchError as error:
            if str(error) == "transport_or_response_failed":
                raise WorkbenchError(
                    f"admission_unknown_reuse_idempotency_key:{key}"
                ) from None
            raise
        self.receipt(
            {
                "event": "admission_readback",
                "idempotency_key": key,
                "run_id": checked_id(result.get("id")),
                "status": result.get("status"),
            }
        )
        return result

    def receipt(self, value: dict):
        private_directory(self.state)
        path = self.state / "receipts.jsonl"
        if path.exists() or path.is_symlink():
            read_private(path, limit=8 * 1024 * 1024)
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "ab") as stream:
            stream.write(
                json.dumps(
                    {"at": time.time(), **value}, allow_nan=False, separators=(",", ":")
                ).encode()
                + b"\n"
            )
            stream.flush()
            os.fsync(stream.fileno())

    def snapshot(self, run_id: str):
        self.authorize()
        return self.request("GET", f"/api/workflows/runs/{checked_id(run_id)}")

    def wait(self, run_id: str, deadline=180):
        if not 1 <= deadline <= 300:
            raise WorkbenchError("invalid_wait_limit")
        stop = time.monotonic() + deadline
        while True:
            result = self.snapshot(run_id)
            if result.get("status") in TERMINAL | {"interrupted"}:
                return result
            if time.monotonic() >= stop:
                raise WorkbenchError(f"wait_expired_run_remains_server_owned:{run_id}")
            time.sleep(min(2, max(0, stop - time.monotonic())))

    def artifact(self, run_id: str, output: Path | None = None):
        data = self.snapshot(run_id)
        metadata = data.get("artifact")
        if (
            data.get("status") != "completed"
            or data.get("accepted") is not True
            or not isinstance(metadata, dict)
            or not re.fullmatch(r"[a-f0-9]{64}", metadata.get("sha256", ""))
            or type(metadata.get("bytes")) is not int
            or not 1 <= metadata["bytes"] <= MAX_JSON
        ):
            raise WorkbenchError("completed_artifact_receipt_required")
        raw = self.request(
            "GET", f"/api/workflows/runs/{checked_id(run_id)}/artifact", binary=True
        )
        digest = hashlib.sha256(raw).hexdigest()
        if len(raw) != metadata["bytes"] or digest != metadata["sha256"]:
            raise WorkbenchError("artifact_readback_mismatch")
        target = output or self.state / "artifacts" / f"{run_id}.{digest[:12]}.json"
        if target.exists() and not target.is_symlink() and read_private(target) == raw:
            return {"saved": str(target.resolve()), "sha256": digest, "bytes": len(raw)}
        write_private(target, raw)
        return {"saved": str(target.resolve()), "sha256": digest, "bytes": len(raw)}

    def benchmark(
        self,
        workflow: str,
        inputs: dict,
        frameworks: list[str],
        *,
        max_calls=18,
        max_output_tokens=24576,
        wait_seconds=180,
    ):
        if (
            not 1 <= len(frameworks) <= 3
            or len(set(frameworks)) != len(frameworks)
            or any(name not in FRAMEWORKS for name in frameworks)
            or not 1 <= max_calls <= 18
            or not 1 <= max_output_tokens <= 24576
        ):
            raise WorkbenchError("finite_benchmark_required")
        status = self.authorize()
        limits = status.get("limits", {})
        calls = limits.get("max_model_calls_per_run")
        tokens = limits.get("max_output_tokens_per_run")
        if (
            type(calls) is not int
            or type(tokens) is not int
            or calls * len(frameworks) > max_calls
            or tokens * len(frameworks) > max_output_tokens
        ):
            raise WorkbenchError("benchmark_server_limits_exceed_ceiling")
        for framework in frameworks:
            if (
                status.get("frameworks", {}).get(framework, {}).get("available")
                is not True
            ):
                raise WorkbenchError("benchmark_framework_unavailable")
        results = []
        experiment = "benchmark_" + uuid.uuid4().hex
        for index, framework in enumerate(frameworks):
            start = time.monotonic()
            admitted = self.run(
                workflow, inputs, framework, key=f"{experiment}_{index}"
            )
            run = self.wait(admitted["id"], wait_seconds)
            artifact = (
                self.artifact(run["id"]) if run.get("status") == "completed" else None
            )
            results.append(
                {
                    "framework": framework,
                    "run_id": run["id"],
                    "status": run["status"],
                    "accepted": run.get("accepted") is True and artifact is not None,
                    "usage": run.get("usage"),
                    "duration_seconds": round(time.monotonic() - start, 3),
                    "artifact": artifact,
                }
            )
        evidence = {
            "experiment": "same_input_framework_worker_comparison",
            "agent_os_platform_benchmark": False,
            "workflow_id": workflow,
            "input_sha256": hashlib.sha256(
                json.dumps(inputs, sort_keys=True, allow_nan=False).encode()
            ).hexdigest(),
            "ceilings": {
                "runs": len(frameworks),
                "model_calls": max_calls,
                "output_tokens": max_output_tokens,
            },
            "results": results,
        }
        target = self.state / "benchmarks" / f"{experiment}.json"
        write_private(target, json.dumps(evidence, allow_nan=False, indent=2).encode())
        return {
            "evidence": str(target.resolve()),
            "executed": len(results),
            "accepted": sum(result["accepted"] for result in results),
            "cost_comparison": "unavailable unless actual per-run costs are present",
        }


def checked_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise WorkbenchError("invalid_run_id")
    return value


def input_file(path: str) -> dict:
    source = Path(path)
    if not source.is_file() or source.is_symlink() or source.stat().st_size > 48000:
        raise WorkbenchError("invalid_input_file")
    try:
        result = json.loads(source.read_bytes())
    except (ValueError, OSError):
        raise WorkbenchError("invalid_input_json") from None
    if not isinstance(result, dict):
        raise WorkbenchError("inputs_must_be_object")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="MomoBot owner workflow workbench; no new queue or provider keys"
    )
    parser.add_argument("--server")
    parser.add_argument(
        "--state-dir", type=Path, default=Path.home() / ".local/state/momo-workbench"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    commands.add_parser("catalog")
    login = commands.add_parser("login")
    login.add_argument("--email", required=True)
    run = commands.add_parser("run")
    run.add_argument("workflow")
    run.add_argument("--inputs", required=True)
    run.add_argument("--framework", choices=FRAMEWORKS, default="langgraph")
    run.add_argument("--idempotency-key")
    run.add_argument("--wait", action="store_true")
    status = commands.add_parser("status")
    status.add_argument("run_id", nargs="?")
    artifact = commands.add_parser("artifact")
    artifact.add_argument("run_id")
    artifact.add_argument("--output", type=Path)
    benchmark = commands.add_parser("benchmark")
    benchmark.add_argument("workflow")
    benchmark.add_argument("--inputs", required=True)
    benchmark.add_argument(
        "--framework", action="append", choices=FRAMEWORKS, required=True
    )
    benchmark.add_argument("--max-model-calls", type=int, default=18)
    benchmark.add_argument("--max-output-tokens", type=int, default=24576)
    args = parser.parse_args(argv)
    try:
        client = WorkbenchClient(configured_server(args.server), args.state_dir)
        if args.command == "doctor":
            result = client.doctor()
        elif args.command == "login":
            result = client.login(
                args.email, getpass.getpass("MomoBot account password: ")
            )
        elif args.command == "catalog":
            catalog = client.catalog()
            result = {
                "total": catalog.get("total"),
                "workflows": [
                    {
                        key: row.get(key)
                        for key in ("id", "title", "category", "requires_browser")
                    }
                    for row in catalog.get("workflows", [])
                ],
            }
        elif args.command == "run":
            admitted = client.run(
                args.workflow,
                input_file(args.inputs),
                args.framework,
                key=args.idempotency_key,
            )
            run = client.wait(admitted["id"]) if args.wait else admitted
            result = {
                key: run.get(key)
                for key in (
                    "id",
                    "workflow_id",
                    "framework",
                    "status",
                    "accepted",
                    "usage",
                    "error",
                )
            }
        elif args.command == "status":
            value = client.snapshot(args.run_id) if args.run_id else client.authorize()
            result = {
                key: value.get(key)
                for key in (
                    "id",
                    "status",
                    "accepted",
                    "usage",
                    "error",
                    "enabled",
                    "frameworks",
                    "limits",
                    "running",
                    "queued",
                )
                if key in value
            }
        elif args.command == "artifact":
            result = client.artifact(args.run_id, args.output)
        else:
            result = client.benchmark(
                args.workflow,
                input_file(args.inputs),
                args.framework,
                max_calls=args.max_model_calls,
                max_output_tokens=args.max_output_tokens,
            )
        print(json.dumps(result, allow_nan=False, indent=2))
        return 0
    except (WorkbenchError, ValueError, OSError) as error:
        message = (
            str(error)
            if isinstance(error, WorkbenchError)
            else "workbench_local_failure"
        )
        print(json.dumps({"error": message}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
