"""Optional placement routes through real host auth and CSRF, all data synthetic."""

import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute
from starlette.testclient import TestClient

# The separately distributed example is not an application dependency.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples/vhin-placement"))
from vhin_placement.api import Service, build_router  # noqa: E402

from app.gateway.client_boundary import is_client_allowed_route  # noqa: E402


def extension_route_calls():
    service = Service({"data_dir": "/synthetic-placement", "organization_id": "placement", "allowed_user_ids": ["owner"], "placement_confirmer_user_ids": ["owner"]})
    for route in build_router(service).routes:
        if isinstance(route, APIRoute):
            path = route.path.replace("{state}", "FL").replace("{asset:path}", "index.html")
            path = re.sub(r"\{[^}]+\}", "x", path)
            for method in route.methods - {"HEAD", "OPTIONS"}:
                yield method, path


def test_optional_placement_route_inventory_is_explicitly_admitted():
    calls = list(extension_route_calls())
    assert len(calls) == 23
    assert all(is_client_allowed_route(method, path) for method, path in calls)


@pytest.fixture
def host(tmp_path, monkeypatch):
    from app.gateway.app import create_app
    from deerflow.config.authorization_config import AuthorizationConfig
    from deerflow.persistence.organizations.resolution import ActiveOrganization

    actor = {"id": "owner", "org": "placement", "member": True}

    async def current_user(request):
        if not request.cookies.get("access_token"):
            return None
        return SimpleNamespace(id=actor["id"], email="synthetic@example.test", system_role="client", needs_setup=False, oauth_provider=None, oauth_id=None)

    async def organization(user_id, selected=None):
        if not actor["member"]:
            return None
        return ActiveOrganization(id=actor["org"], name="Synthetic workspace", role="client", storage_user_id="storage-user")

    monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", current_user)
    monkeypatch.setattr("app.gateway.auth_middleware._resolve_active_workspace", organization)
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: AuthorizationConfig())
    service = Service({"data_dir": str(tmp_path), "organization_id": "placement", "allowed_user_ids": ["owner", "coordinator"], "placement_confirmer_user_ids": ["owner"]})
    service.ready = True
    app = create_app()
    app.include_router(build_router(service))
    # No lifespan: repository/provider/model startup is outside this HTTP fixture.
    client = TestClient(app, cookies={"access_token": "synthetic-session", "csrf_token": "synthetic-csrf"})
    return client, actor


def test_client_placement_read_write_retains_host_identity_and_csrf(host):
    client, _ = host
    assert client.get("/api/vhin/state").status_code == 200
    assert client.get("/api/vhin/dashboard/").status_code == 200
    assert client.get("/api/vhin/dashboard/app.js").status_code == 200
    assert client.get("/api/vhin/recommendations").status_code == 200
    data = {"name": "Synthetic community", "city": "Tampa", "services": [], "source_url": "https://example.test/community", "observed_at": "2026-11-06T12:00:00+00:00"}
    headers = {"Idempotency-Key": "synthetic-community"}
    assert client.post("/api/vhin/communities", json=data, headers=headers).status_code == 403
    headers["X-CSRF-Token"] = "wrong"
    assert client.post("/api/vhin/communities", json=data, headers=headers).status_code == 403
    headers["X-CSRF-Token"] = "synthetic-csrf"
    saved = client.post("/api/vhin/communities", json=data, headers=headers)
    assert saved.status_code == 201, saved.text
    cid = saved.json()["id"]
    assert client.get("/api/vhin/state").json()["communities"][0]["id"] == cid
    contract = {"status": "contracted", "agreement_ref": "synthetic-agreement", "human_confirmed": True}
    headers["Idempotency-Key"] = "synthetic-contract"
    assert client.post(f"/api/vhin/communities/{cid}/contract", json=contract, headers=headers).status_code == 200
    headers["Idempotency-Key"] = "synthetic-rating"
    assert client.post(f"/api/vhin/communities/{cid}/rating", json={"stars": 3}, headers=headers).status_code == 200


def test_placement_host_denies_missing_membership_foreign_org_and_unlisted_actor(host):
    client, actor = host
    for changes in ({"id": "outsider"}, {"org": "other-workspace"}, {"member": False}):
        original = actor.copy()
        actor.update(changes)
        for path in ("/api/vhin/state", "/api/vhin/dashboard/", "/api/vhin/recommendations", "/api/vhin/regulations"):
            assert client.get(path).status_code == 403
        actor.update(original)
    client.cookies.clear()
    assert client.get("/api/vhin/state").status_code == 401


def test_client_regulation_routes_accept_either_state_case_through_host(host):
    client, _ = host
    for path in ("/api/vhin/regulations/FL/search?q=medication", "/api/vhin/regulations/fl/search?q=medication", "/api/vhin/regulations/fl/unit?citation=Rule%2059A-36.006"):
        assert client.get(path).status_code not in (401, 403), path
    assert client.get("/api/vhin/regulations/fl/config").status_code == 403


def test_coordinator_cannot_assert_owner_authority_through_host(host):
    client, actor = host
    actor["id"] = "coordinator"
    assert client.get("/api/vhin/state").status_code == 200
    headers = {"Idempotency-Key": "synthetic-denied", "X-CSRF-Token": "synthetic-csrf"}
    assert client.post("/api/vhin/communities/x/rating", json={"stars": 3}, headers=headers).status_code == 403
    assert client.post("/api/vhin/communities/x/contract", json={"status": "contracted", "agreement_ref": "synthetic", "human_confirmed": True}, headers=headers).status_code == 403


@pytest.mark.parametrize(
    "method,path",
    [
        ("DELETE", "/api/vhin/referrals/x"),
        ("PUT", "/api/vhin/state"),
        ("POST", "/api/vhin/send"),
        ("GET", "/api/vhin/admin"),
        ("GET", "/api/vhin/dashboard/secrets.json"),
        ("POST", "/api/vhin/tour-plans/x/book"),
        ("GET", "/api/vhin/regulations/FL/config"),
        ("GET", "/api/vhin/regulations/fl/config"),
        ("GET", "/api/vhin/regulations/fla/search"),
    ],
)
def test_placement_unknown_and_external_side_effect_routes_stay_closed(method, path):
    assert not is_client_allowed_route(method, path)


def test_operator_public_origin_is_explicit_and_not_a_wildcard(monkeypatch):
    import yaml
    from starlette.requests import Request

    from app.gateway.csrf_middleware import is_allowed_auth_origin

    root = Path(__file__).resolve().parents[2]
    overlay = yaml.safe_load((root / "deploy/momentum/ec2/compose.ec2.yaml").read_text())
    assert "GATEWAY_CORS_ORIGINS=${GATEWAY_CORS_ORIGINS:-}" in overlay["services"]["gateway"]["environment"]

    def auth_request(origin):
        return Request({"type": "http", "method": "POST", "scheme": "http", "path": "/api/v1/auth/login/local", "query_string": b"", "server": ("gateway", 8001), "headers": [(b"host", b"gateway:8001"), (b"origin", origin.encode())]})

    monkeypatch.setenv("GATEWAY_CORS_ORIGINS", "https://public.example.test")
    assert is_allowed_auth_origin(auth_request("https://public.example.test"))
    assert not is_allowed_auth_origin(auth_request("https://foreign.example.test"))
    monkeypatch.setenv("GATEWAY_CORS_ORIGINS", "*")
    assert not is_allowed_auth_origin(auth_request("https://public.example.test"))
