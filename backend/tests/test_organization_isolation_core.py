"""M3 lane 0 core: active-organization resolution and write stamping."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, Request
from org_isolation_fixtures import ORG_A, ORG_B, ORG_S, STORAGE_S, USER_A, USER_B, USER_C, acting_as, auth_headers, org_world  # noqa: F401

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.internal_auth import create_internal_auth_headers
from deerflow.persistence.organizations.resolution import OrganizationMismatchError, organization_for_write
from deerflow.runtime.user_context import AUTO, resolve_organization_id, resolve_user_id


@pytest.mark.asyncio
async def test_world_and_active_organization_match_real_auth_middleware(org_world):  # noqa: F811
    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/api/proof")
    async def proof(request: Request):
        return {"actor": str(request.state.user.id), "storage": resolve_user_id(AUTO), "organization": resolve_organization_id()}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:

        async def who(headers):
            response = await client.get("/api/proof", headers=headers)
            return response.json() if response.status_code == 200 else response.status_code

        assert await who(auth_headers(USER_A)) == {"actor": USER_A, "storage": USER_A, "organization": ORG_A}
        assert await who(auth_headers(USER_A, ORG_S)) == {"actor": USER_A, "storage": STORAGE_S, "organization": ORG_S}
        assert await who(auth_headers(USER_C, ORG_S)) == {"actor": USER_C, "storage": STORAGE_S, "organization": ORG_S}
        assert await who(auth_headers(USER_B, ORG_S)) == 403
        # Phase 1 keeps header-only internal calls working; they carry no organization boundary.
        assert await who(create_internal_auth_headers(owner_user_id=USER_A)) == {"actor": USER_A, "storage": USER_A, "organization": None}

    with acting_as(USER_C, ORG_S):
        assert (resolve_user_id(AUTO), resolve_organization_id()) == (STORAGE_S, ORG_S)
    assert resolve_organization_id() is None


@pytest.mark.parametrize(
    ("active", "parent", "storage", "expected"),
    [
        (ORG_A, None, USER_A, ORG_A),  # direct row in the caller's private organization
        (ORG_S, ORG_S, STORAGE_S, ORG_S),  # child of a verified parent in the shared workspace
        (None, ORG_S, STORAGE_S, ORG_S),  # internal caller inherits its verified parent
        (None, None, USER_A, None),  # nothing proves an organization: keep the NULL quarantine
    ],
)
def test_organization_for_write_returns_the_server_resolved_organization(active, parent, storage, expected):
    assert organization_for_write(active, parent, storage) == expected


@pytest.mark.parametrize(
    ("active", "parent", "storage"),
    [
        (ORG_A, ORG_B, USER_A),  # attach under another organization's parent
        (ORG_S, ORG_S, USER_A),  # actor passed where S's storage principal belongs
        (ORG_S, None, USER_A),  # the same mix-up on a direct row
        (None, ORG_B, USER_A),  # internal caller writing under a foreign parent
        (ORG_A, None, None),  # no storage principal proves no organization
    ],
)
def test_organization_for_write_refuses_any_mismatch_as_not_found(active, parent, storage):
    with pytest.raises(OrganizationMismatchError) as exc_info:
        organization_for_write(active, parent, storage)
    assert isinstance(exc_info.value, LookupError)
