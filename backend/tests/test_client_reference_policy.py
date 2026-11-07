"""Explicit reference reads under a real client projects:read denial, all synthetic."""

from types import SimpleNamespace

import pytest
from org_isolation_fixtures import ORG_S, USER_A, USER_B, USER_C, auth_headers, org_world  # noqa: F401
from test_org_isolation_a_projects import _build_app, _client, _create_project, _isolate_paths, _upload_document  # noqa: F401

from app.gateway.deps import get_config
from app.gateway.routers import client_references
from deerflow.config.authorization_config import AuthorizationConfig


def clients_with_project_denial(monkeypatch):
    async def user(request):
        return SimpleNamespace(id=request.cookies["access_token"], system_role="client", email="synthetic@example.test")

    config = AuthorizationConfig.model_validate(
        {"enabled": True, "provider": {"use": "deerflow.authz.rbac:RbacAuthorizationProvider", "config": {"roles": {"client": {"routes": {"allow": "*", "deny": ["projects:read", "projects:write", "projects:delete"]}}}}}}
    )
    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", user)
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: config)


@pytest.mark.asyncio
async def test_exact_actor_workspace_and_document_grant_preserves_global_project_deny(org_world, monkeypatch):  # noqa: F811
    app = _build_app(org_world)
    app.include_router(client_references.router)
    async with _client(app) as client:
        project = await _create_project(client, auth_headers(USER_A, ORG_S), "Approved reference")
        other_project = await _create_project(client, auth_headers(USER_A, ORG_S), "Unapproved workspace project")
        foreign = await _create_project(client, auth_headers(USER_B), "Foreign project")
        doc = await _upload_document(client, project["id"], auth_headers(USER_A, ORG_S), "reference.txt", b"Approved public facts")
        hidden_doc = await _upload_document(client, project["id"], auth_headers(USER_A, ORG_S), "staff-only.txt", b"Not approved")
        config = SimpleNamespace(client_reference_reads={"enabled": True, "bindings": [{"user_id": USER_A, "organization_id": ORG_S, "project_id": project["id"], "documents": {doc["id"]: doc["sha256"]}}]})
        app.dependency_overrides[get_config] = lambda: config
        clients_with_project_denial(monkeypatch)
        headers = auth_headers(USER_A, ORG_S)
        listing = await client.get("/api/client-references/projects", headers=headers)
        assert listing.status_code == 200
        assert listing.json() == {"projects": [{"id": project["id"], "name": project["name"], "status": "active"}]}
        assert (await client.get(f"/api/client-references/projects/{project['id']}", headers=headers)).json() == listing.json()["projects"][0]
        docs = await client.get(f"/api/client-references/projects/{project['id']}/documents", headers=headers)
        assert docs.status_code == 200
        assert docs.json()["total"] == 1
        assert set(docs.json()["documents"][0]) == {"id", "name", "sha256", "size_bytes", "content_missing"}
        assert docs.json()["documents"][0]["id"] == doc["id"]
        content = await client.get(f"/api/client-references/projects/{project['id']}/documents/{doc['id']}/content", headers=headers)
        assert content.status_code == 200 and content.content == b"Approved public facts"
        assert content.headers["content-disposition"].startswith("attachment;")
        assert content.headers["cache-control"] == "no-store"
        assert content.headers["x-content-type-options"] == "nosniff"
        # The provider's original deny is still authoritative on staff project APIs.
        assert (await client.get("/api/projects", headers=headers)).status_code == 403
        assert (await client.get(f"/api/projects/{project['id']}/documents", headers=headers)).status_code == 403
        for pid in (other_project["id"], foreign["id"]):
            assert (await client.get(f"/api/client-references/projects/{pid}/documents", headers=headers)).status_code == 404
        assert (await client.get(f"/api/client-references/projects/{project['id']}/documents/{hidden_doc['id']}/content", headers=headers)).status_code == 404
        assert (await client.get("/api/client-references/projects", headers=auth_headers(USER_C, ORG_S))).status_code == 403
        assert (await client.get("/api/client-references/projects", headers=auth_headers(USER_A))).status_code == 403
        forged = {**auth_headers(USER_C, ORG_S), "X-DeerFlow-Owner-User-Id": USER_A}
        assert (await client.get("/api/client-references/projects?user_id=" + USER_A, headers=forged)).status_code == 403
        assert (await client.get("/api/client-references/projects")).status_code == 401
        for method, path in [
            ("POST", "/api/client-references/projects"),
            ("DELETE", f"/api/client-references/projects/{project['id']}"),
            ("GET", f"/api/client-references/projects/{project['id']}/threads"),
            ("GET", "/api/client-references/config"),
        ]:
            assert (await client.request(method, path, headers=headers)).status_code == 403
        from sqlalchemy import update

        from deerflow.persistence.organizations.model import OrganizationMemberRow

        async with org_world() as session, session.begin():
            await session.execute(update(OrganizationMemberRow).where(OrganizationMemberRow.user_id == USER_A, OrganizationMemberRow.organization_id == ORG_S).values(status="inactive"))
        assert (await client.get("/api/client-references/projects", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_hash_bound_download_rejects_same_size_content_change(org_world, monkeypatch):  # noqa: F811
    from org_isolation_fixtures import acting_as

    from deerflow.config.paths import get_paths
    from deerflow.projects.documents import resolve_document_paths

    app = _build_app(org_world)
    app.include_router(client_references.router)
    async with _client(app) as client:
        project = await _create_project(client, auth_headers(USER_A, ORG_S))
        doc = await _upload_document(client, project["id"], auth_headers(USER_A, ORG_S), "safe.txt", b"Original")
        cfg = SimpleNamespace(client_reference_reads={"enabled": True, "bindings": [{"user_id": USER_A, "organization_id": ORG_S, "project_id": project["id"], "documents": {doc["id"]: doc["sha256"]}}]})
        app.dependency_overrides[get_config] = lambda: cfg
        with acting_as(USER_A, ORG_S):
            row = await app.state.project_document_repo.get(doc["id"])
            path, _ = resolve_document_paths(get_paths(), user_id="storage-s", relpath=row["stored_relpath"], name=row["name"])
        path.write_bytes(b"Tampered")
        clients_with_project_denial(monkeypatch)
        headers = auth_headers(USER_A, ORG_S)
        response = await client.get(f"/api/client-references/projects/{project['id']}/documents/{doc['id']}/content", headers=headers)
        assert response.status_code == 409
        listing = await client.get(f"/api/client-references/projects/{project['id']}/documents", headers=headers)
        assert listing.json()["documents"][0]["content_missing"] is True
        cfg.client_reference_reads["bindings"][0]["documents"][doc["id"]] = "0" * 64
        assert (await client.get(f"/api/client-references/projects/{project['id']}/documents/{doc['id']}/content", headers=headers)).status_code == 404
        assert (await client.get(f"/api/client-references/projects/{project['id']}/documents", headers=headers)).json()["total"] == 0


@pytest.mark.parametrize("changed", [{"enabled": "true"}, {"bindings": [{"user_id": "../actor"}]}, {"wildcard": "*"}])
def test_malformed_policy_does_not_coerce_authority(changed):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        client_references.ReferencePolicy.model_validate(changed)


@pytest.mark.asyncio
async def test_policy_is_disabled_by_default_and_unknown_configuration_fails_closed(org_world, monkeypatch):  # noqa: F811
    app = _build_app(org_world)
    app.include_router(client_references.router)
    clients_with_project_denial(monkeypatch)
    cfg = SimpleNamespace(client_reference_reads=None)
    app.dependency_overrides[get_config] = lambda: cfg
    async with _client(app) as client:
        assert (await client.get("/api/client-references/projects", headers=auth_headers(USER_A, ORG_S))).status_code == 403
        cfg.client_reference_reads = {"enabled": True, "bindings": [], "unexpected": "deny"}
        assert (await client.get("/api/client-references/projects", headers=auth_headers(USER_A, ORG_S))).status_code == 503
