"""Offline tests for the owner-scoped CLI; no live server or provider calls."""

import hashlib
import http.cookiejar
import importlib.util
import io
import json
import stat
import urllib.error
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("momo_workbench", Path(__file__).resolve().parents[2] / "scripts/momo_workbench.py")
workbench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workbench)
SCOPE = "a" * 64
SERVER = "https://momo.example"


class Response(io.BytesIO):
    def __init__(self, value, url):
        super().__init__(value if isinstance(value, bytes) else json.dumps(value).encode())
        self.url = url

    def geturl(self):
        return self.url


class Opener:
    def __init__(self, value=None, *, target=None, error=None):
        self.value = value or {"ok": True}
        self.target = target
        self.error = error
        self.calls = []

    def open(self, request, timeout):
        self.calls.append(request)
        if self.error:
            raise self.error
        return Response(self.value, self.target or request.full_url)


def cookie(name, value="synthetic", domain="momo.example"):
    return http.cookiejar.Cookie(
        version=0,
        port=None,
        port_specified=False,
        name=name,
        value=value,
        domain=domain,
        domain_specified=False,
        domain_initial_dot=False,
        path="/",
        path_specified=True,
        secure=True,
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest={},
    )


def client(tmp_path, **kwargs):
    return workbench.WorkbenchClient(SERVER, tmp_path / "private", **kwargs)


@pytest.mark.parametrize(
    "endpoint", ["http://remote.example", "https://user:password@momo.example", "https://momo.example?key=secret", "https://momo.example#token", "https://momo.example:70000", "https://momo.example/admin", "https://momo.example."]
)
def test_endpoint_rejects_remote_http_credentials_and_ambiguous_routes(endpoint):
    with pytest.raises(workbench.WorkbenchError, match="invalid_server_endpoint"):
        workbench.server_origin(endpoint)


@pytest.mark.parametrize("endpoint,expected", [("http://127.0.0.1:3040/workspace/workflows", "http://127.0.0.1:3040"), ("https://momo.example/workspace/openai", SERVER)])
def test_endpoint_accepts_safe_installed_app_paths(endpoint, expected):
    assert workbench.server_origin(endpoint) == expected


def test_doctor_uses_public_auth_probe_behind_installed_frontend(tmp_path):
    class FrontendOpener(Opener):
        def open(self, request, timeout):
            self.calls.append(request)
            if request.full_url.endswith("/health"):
                raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, io.BytesIO(b""))
            assert request.full_url == SERVER + workbench.AUTH + "/setup-status"
            return Response({"needs_setup": False}, request.full_url)

    opener = FrontendOpener()
    instance = client(tmp_path, opener=opener)
    value = instance.doctor()
    assert value["gateway"] == {"reachable": True, "auth_configured": True, "probe": "auth_setup_status"}
    assert value["authentication"] == "sign_in_required"
    assert value["automatic_execution"] is False
    assert len(opener.calls) == 2
    assert not instance.auth_file.exists()


def test_doctor_does_not_mask_transport_failure_or_invent_setup_state(tmp_path):
    instance = client(tmp_path, opener=Opener(error=urllib.error.HTTPError(SERVER, 502, "Bad Gateway", {}, io.BytesIO(b""))))
    with pytest.raises(workbench.WorkbenchError, match="http_502"):
        instance.doctor()
    assert len(instance.opener.calls) == 1


def test_private_saved_auth_permissions_symlink_and_origin_are_enforced(tmp_path):
    state = tmp_path / "private"
    workbench.private_directory(state)
    path = state / "auth.json"
    record = {"server": SERVER, "user_id": "owner", "scope": SCOPE, "cookies": [{"name": "momo_agent_access_token", "value": "synthetic", "domain": "other.example", "path": "/"}]}
    path.write_text(json.dumps(record))
    path.chmod(0o644)
    with pytest.raises(workbench.WorkbenchError, match="permissions"):
        client(tmp_path)
    path.chmod(0o600)
    with pytest.raises(workbench.WorkbenchError, match="origin_mismatch"):
        client(tmp_path)
    path.unlink()
    path.symlink_to(tmp_path / "absent")
    with pytest.raises(workbench.WorkbenchError, match="private_file_unavailable"):
        client(tmp_path)


def test_api_response_keeps_exact_origin_and_mutations_have_csrf_scope(tmp_path):
    opener = Opener()
    instance = client(tmp_path, opener=opener)
    instance.scope = SCOPE
    instance.jar.set_cookie(cookie("csrf_token", "csrf_synthetic"))
    assert instance.request("POST", "/api/workflows/runs", {"inputs": {}}, headers={"Idempotency-Key": "cli_1"}) == {"ok": True}
    headers = {name.lower(): value for name, value in opener.calls[0].header_items()}
    assert headers["origin"] == SERVER
    assert headers["x-csrf-token"] == "csrf_synthetic"
    assert headers["x-expected-workflow-scope"] == SCOPE
    assert headers["idempotency-key"] == "cli_1"
    opener.target = "https://other.example/api/workflows/runs"
    with pytest.raises(workbench.WorkbenchError, match="origin_mismatch"):
        instance.request("GET", "/api/workflows/runs")


def test_redirect_and_large_or_private_error_body_are_not_exposed(tmp_path):
    with pytest.raises(workbench.WorkbenchError, match="redirect_rejected"):
        workbench.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example")
    instance = client(tmp_path, opener=Opener(b"x" * (workbench.MAX_JSON + 1)))
    with pytest.raises(workbench.WorkbenchError, match="response_too_large"):
        instance.request("GET", "/health")
    instance.opener = Opener(error=urllib.error.HTTPError(SERVER, 401, "private-password", {}, io.BytesIO(b"private-token")))
    with pytest.raises(workbench.WorkbenchError) as captured:
        instance.request("GET", "/api/workflows/runs")
    assert str(captured.value) == "http_401"


def test_full_catalog_uses_its_own_finite_response_bound(tmp_path):
    payload = {"workflows": [], "padding": "x" * (workbench.MAX_JSON + 4000)}
    instance = client(tmp_path, opener=Opener(payload))
    assert instance.request("GET", "/api/workflows/catalog")["workflows"] == []
    instance.opener = Opener({"padding": "x" * (1024 * 1024)})
    with pytest.raises(workbench.WorkbenchError, match="response_too_large"):
        instance.request("GET", "/api/workflows/catalog")


def test_changed_actor_or_org_scope_blocks_admission_before_post(tmp_path):
    instance = client(tmp_path)
    instance.user_id, instance.scope = "owner", SCOPE
    calls = []

    def request(method, path, *args, **kwargs):
        calls.append((method, path))
        return {"id": "owner"} if path.endswith("/me") else {"owner_scope": "b" * 64}

    instance.request = request
    with pytest.raises(workbench.WorkbenchError, match="owner_scope_changed"):
        instance.run("recipe", {}, "langgraph")
    assert all(method == "GET" for method, _path in calls)
    instance.request = lambda *args, **kwargs: {"id": "different"}
    with pytest.raises(workbench.WorkbenchError, match="owner_identity_changed"):
        instance.authorize()


def test_mfa_login_saves_only_scoped_cookies_mode0600_without_challenge(tmp_path):
    instance = client(tmp_path)
    calls = []

    def request(method, path, body=None, **kwargs):
        calls.append((method, path, body))
        if path.endswith("/login/local"):
            return {"mfa_required": True, "challenge": "challenge_synthetic"}
        if path.endswith("/login/mfa"):
            instance.jar.set_cookie(cookie("momo_agent_access_token", "token_synthetic"))
            instance.jar.set_cookie(cookie("csrf_token"))
            instance.jar.set_cookie(cookie("unrelated", "do_not_save"))
            return {"ok": True}
        return {"id": "owner"} if path.endswith("/me") else {"owner_scope": SCOPE}

    instance.request = request
    assert instance.login("owner@example.test", "password_synthetic", lambda _: "123456") == {"authenticated": True, "owner_id": "owner"}
    saved = json.loads(instance.auth_file.read_bytes())
    assert {row["name"] for row in saved["cookies"]} == {"momo_agent_access_token", "csrf_token"}
    assert stat.S_IMODE(instance.auth_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(instance.state.stat().st_mode) == 0o700
    assert "challenge_synthetic" not in instance.auth_file.read_text()
    assert "password_synthetic" not in instance.auth_file.read_text()
    restored = client(tmp_path)
    assert restored.user_id == "owner" and restored.scope == SCOPE
    assert [row.value for row in restored.jar if row.name == "momo_agent_access_token"] == ["token_synthetic"]


def test_unknown_admission_is_one_post_and_retains_same_idempotency_receipt(tmp_path):
    instance = client(tmp_path)
    instance.authorize = lambda: setattr(instance, "scope", SCOPE)
    calls = []

    def request(method, path, body, **kwargs):
        calls.append((method, path, kwargs))
        raise workbench.WorkbenchError("transport_or_response_failed")

    instance.request = request
    with pytest.raises(workbench.WorkbenchError, match="admission_unknown_reuse_idempotency_key:cli_fixed"):
        instance.run("recipe", {"text": "same"}, "langgraph", key="cli_fixed")
    assert len(calls) == 1
    receipt = json.loads((instance.state / "receipts.jsonl").read_text())
    assert receipt["idempotency_key"] == "cli_fixed" and receipt["event"] == "admission_requested"
    assert "same" not in json.dumps(receipt)


def test_artifact_requires_accepted_digest_readback_and_never_overwrites(tmp_path):
    instance = client(tmp_path)
    raw = b'{"useful":"accepted result"}'
    digest = hashlib.sha256(raw).hexdigest()
    instance.snapshot = lambda _: {"status": "completed", "accepted": True, "artifact": {"sha256": digest, "bytes": len(raw)}}
    instance.request = lambda *args, **kwargs: b"wrong bytes"
    with pytest.raises(workbench.WorkbenchError, match="readback_mismatch"):
        instance.artifact("run_1")
    assert not (instance.state / "artifacts").exists()
    instance.request = lambda *args, **kwargs: raw
    saved = instance.artifact("run_1")
    target = Path(saved["saved"])
    assert target.read_bytes() == raw and stat.S_IMODE(target.stat().st_mode) == 0o600
    assert instance.artifact("run_1") == saved
    target.write_bytes(b"owner-existing-content")
    with pytest.raises(workbench.WorkbenchError, match="output_exists"):
        instance.artifact("run_1")
    assert target.read_bytes() == b"owner-existing-content"


def test_benchmark_enforces_three_runs_server_ceilings_and_same_inputs(tmp_path):
    instance = client(tmp_path)
    status = {"limits": {"max_model_calls_per_run": 6, "max_output_tokens_per_run": 8192}, "frameworks": {name: {"available": True} for name in workbench.FRAMEWORKS}}
    instance.authorize = lambda: status
    admissions = []

    def run(workflow, inputs, framework, *, key):
        admissions.append((workflow, inputs, framework, key))
        return {"id": "run_" + framework}

    instance.run = run
    instance.wait = lambda run_id, *_: {"id": run_id, "status": "completed", "accepted": True, "usage": {"cost": None}}
    instance.artifact = lambda run_id: {"sha256": "c" * 64, "bytes": 12, "saved": run_id}
    with pytest.raises(workbench.WorkbenchError, match="finite_benchmark"):
        instance.benchmark("recipe", {}, list(workbench.FRAMEWORKS[:4]))
    with pytest.raises(workbench.WorkbenchError, match="limits_exceed"):
        instance.benchmark("recipe", {}, ["langgraph", "crewai"], max_calls=6)
    assert not admissions
    inputs = {"task": "same held-out input"}
    result = instance.benchmark("recipe", inputs, ["langgraph", "crewai", "mastra"])
    assert len(admissions) == 3 and all(row[1] is inputs for row in admissions)
    assert len({row[3] for row in admissions}) == 3
    evidence = json.loads(Path(result["evidence"]).read_text())
    assert evidence["agent_os_platform_benchmark"] is False
    assert evidence["ceilings"]["runs"] == 3 and result["accepted"] == 3
    assert "same held-out input" not in json.dumps(evidence)


def test_help_has_no_auth_install_or_provider_execution(capsys):
    with pytest.raises(SystemExit) as captured:
        workbench.main(["--help"])
    assert captured.value.code == 0
    assert "benchmark" in capsys.readouterr().out
