"""Shared-workspace branding: authorization, validation, persistence, reset.



Runs the real AuthMiddleware and real SQL, mirroring

``test_shared_workspace_membership.py``. Disposable file-backed SQLite only; never the live

database.

"""

from __future__ import annotations

import asyncio
import base64
import pathlib
import struct
import tempfile
import zlib
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import workspace_branding, workspaces
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.persistence.base import Base
from deerflow.persistence.organizations.branding import OrganizationBrandingRow
from deerflow.persistence.organizations.identity import private_organization_id, private_organization_slug
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.user.model import UserRow

SHARED_ID = "workspace-1"

OWNER, ADMIN, OUTSIDER = "actor-owner", "actor-admin", "actor-outsider"
#: Active member whose role is outside _EDIT_ROLES: may read, may not write.
VIEWER = "actor-viewer"


def _png(width: int, height: int) -> str:
    """Smallest valid PNG carrying real IHDR dimensions."""

    def chunk(tag: bytes, payload: bytes) -> bytes:

        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)

    raw = b"\x89PNG\r\n\x1a\n"

    raw += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))

    raw += chunk(b"IDAT", zlib.compress(b"\x00" * (width * height * 4 + height)))

    raw += chunk(b"IEND", b"")

    return "data:image/png;base64," + base64.b64encode(raw).decode()


def _real(pil_format: str, mime: str, size: tuple[int, int] = (32, 32)) -> str:
    """A genuine, fully decodable image produced by the same library."""

    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()

    Image.new("RGB", size, (16, 90, 200)).save(buffer, format=pil_format)

    return f"data:image/{mime};base64," + base64.b64encode(buffer.getvalue()).decode()


def _fake_webp() -> str:
    """A RIFF/WEBP container with no real VP8 payload."""
    blob = b"RIFF" + bytes(4) + b"WEBP" + bytes(20)
    return "data:image/webp;base64," + base64.b64encode(blob).decode()


def _truncated_png() -> str:
    """A valid PNG whose payload is cut in half: header parsing would pass."""

    raw = base64.b64decode(_png(64, 64).split(",", 1)[1])

    return "data:image/png;base64," + base64.b64encode(raw[: len(raw) // 2]).decode()


def _header_only_png() -> str:
    """Signature plus a well-formed IHDR and nothing else."""

    raw = base64.b64decode(_png(64, 64).split(",", 1)[1])

    return "data:image/png;base64," + base64.b64encode(raw[:33]).decode()


def _bomb_png() -> str:
    """A 68-byte PNG header declaring dimensions past Pillow's bomb threshold.

    Nothing large is allocated or compressed: only IHDR carries the huge values,
    and Pillow raises inside ``Image.open()`` while still reading the header.
    """

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)

    raw = b"\x89PNG\r\n\x1a\n"
    raw += chunk(b"IHDR", struct.pack(">IIBBBBB", 60000, 60000, 8, 6, 0, 0, 0))
    raw += chunk(b"IDAT", zlib.compress(b"\x00" * 16))
    raw += chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(raw).decode()


@pytest_asyncio.fixture()
async def branding_db(monkeypatch):

    # A real file-backed database, not in-memory with StaticPool: the
    # concurrency tests need two genuinely separate connections. Sharing one
    # connection lets a loser's rollback discard the winner's work, which is a
    # harness artifact and made the initial-insert race flaky.
    tmp = tempfile.mkdtemp(prefix="branding-db-")
    engine = create_async_engine(f"sqlite+aiosqlite:///{pathlib.Path(tmp, 'branding.sqlite').as_posix()}")

    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync: Base.metadata.create_all(
                sync,
                tables=[
                    UserRow.__table__,
                    OrganizationRow.__table__,
                    OrganizationMemberRow.__table__,
                    OrganizationBrandingRow.__table__,
                ],
            )
        )

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session, session.begin():
        session.add(OrganizationRow(id=SHARED_ID, slug="momentum", name="Momentum", status="active", storage_user_id="storage-owner"))

        session.add(OrganizationMemberRow(organization_id=SHARED_ID, user_id=OWNER, role="owner", status="active"))

        session.add(OrganizationMemberRow(organization_id=SHARED_ID, user_id=ADMIN, role="admin", status="active"))

        session.add(OrganizationMemberRow(organization_id=SHARED_ID, user_id=VIEWER, role="member", status="active"))

        for actor in (OWNER, ADMIN, VIEWER, OUTSIDER):
            private = private_organization_id(actor)

            session.add(OrganizationRow(id=private, slug=private_organization_slug(actor), name="Private", status="active"))

            session.add(OrganizationMemberRow(organization_id=private, user_id=actor, role="owner", status="active"))

    yield factory

    await engine.dispose()


@pytest_asyncio.fixture()
async def client(branding_db, monkeypatch):

    async def authenticated_actor(request):

        return SimpleNamespace(id=request.cookies["access_token"], system_role="user", email="a@example.com")

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "")

    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", authenticated_actor)

    monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", lambda: branding_db)

    monkeypatch.setattr(workspaces, "get_session_factory", lambda: branding_db)

    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: AuthorizationConfig())

    app = FastAPI()

    app.add_middleware(AuthMiddleware)

    app.include_router(workspaces.router)

    app.include_router(workspace_branding.router)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        yield http


def _as(actor: str) -> dict[str, str]:

    return {"Cookie": f"access_token={actor}"}


def _url(workspace_id: str = SHARED_ID) -> str:

    return f"/api/workspaces/{workspace_id}/branding"


@pytest.mark.asyncio
async def test_member_reads_defaults_before_anything_is_set(client):

    result = await client.get(_url(), headers=_as(ADMIN))

    assert result.status_code == 200

    body = result.json()

    # A missing row is defaults, not an error, and the workspace name is the fallback.

    assert body["brand_name"] is None and body["logo"] is None

    assert body["treatment"] == "current" and body["version"] == 0

    assert body["workspace_name"] == "Momentum" and body["can_edit"] is True


@pytest.mark.asyncio
async def test_outsider_who_knows_the_id_gets_404_not_403(client):

    # Membership, not knowledge of the id, is the authorization input; 404 so

    # the response does not confirm the workspace exists.

    assert (await client.get(_url(), headers=_as(OUTSIDER))).status_code == 404

    assert (await client.put(_url(), headers=_as(OUTSIDER), json={"brand_name": "Theirs", "treatment": "classic"})).status_code == 404

    assert (await client.delete(_url() + "?expected_version=0", headers=_as(OUTSIDER))).status_code == 404


@pytest.mark.asyncio
async def test_private_workspace_has_no_branding(client):

    # Branding is a shared-workspace concept; the actor's own private org 404s.

    assert (await client.get(_url(private_organization_id(OWNER)), headers=_as(OWNER))).status_code == 404


@pytest.mark.asyncio
async def test_owner_writes_and_member_reads_back(client, branding_db):

    logo = _png(128, 128)

    saved = await client.put(_url(), headers=_as(OWNER), json={"brand_name": "  Momentum 360  ", "logo": logo, "treatment": "paper"})

    assert saved.status_code == 200

    body = saved.json()

    assert body["brand_name"] == "Momentum 360"  # trimmed

    assert body["treatment"] == "paper" and body["version"] == 1 and body["updated_at"] is not None

    read = await client.get(_url(), headers=_as(ADMIN))

    assert read.status_code == 200 and read.json()["logo"] == logo

    async with branding_db() as session:
        row = await session.get(OrganizationBrandingRow, SHARED_ID)

        # The acting person is recorded, never the workspace storage principal.

        assert row.updated_by == OWNER and row.updated_by != "storage-owner"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"logo": "https://example.com/logo.png", "treatment": "current"}, 415),
        ({"logo": "data:image/svg+xml;base64,PHN2Zy8+", "treatment": "current"}, 415),
        # A JPEG data URI whose bytes are actually a PNG: declared type is never trusted.
        ({"logo": "data:image/jpeg;base64," + _png(8, 8).split(",", 1)[1], "treatment": "current"}, 415),
        ({"logo": "data:image/png;base64,not-base64!!", "treatment": "current"}, 415),
        ({"logo": _png(1024, 16), "treatment": "current"}, 413),
        ({"brand_name": "   ", "treatment": "current"}, 422),
        ({"treatment": "neon"}, 409),
    ],
)
async def test_malformed_payloads_are_rejected(client, branding_db, payload, expected):

    assert (await client.put(_url(), headers=_as(OWNER), json=payload)).status_code == expected

    async with branding_db() as session:
        # A rejected payload must not create a row or bump the version.

        assert await session.get(OrganizationBrandingRow, SHARED_ID) is None


@pytest.mark.asyncio
async def test_reset_clears_fields_and_keeps_version_monotonic(client):

    await client.put(_url(), headers=_as(OWNER), json={"brand_name": "Momentum", "logo": _png(64, 64), "treatment": "classic"})

    reset = await client.delete(_url(), headers=_as(ADMIN))

    assert reset.status_code == 200

    body = reset.json()

    assert body["brand_name"] is None and body["logo"] is None

    assert body["treatment"] == "current"

    assert body["version"] == 2  # monotonic across reset, so a stale version cannot replay


@pytest.mark.asyncio
async def test_expected_version_conflict_is_412(client):

    await client.put(_url(), headers=_as(OWNER), json={"brand_name": "First", "treatment": "current"})

    stale = await client.put(_url(), headers=_as(OWNER), json={"brand_name": "Second", "treatment": "current", "expected_version": 0})

    assert stale.status_code == 412

    fresh = await client.put(_url(), headers=_as(OWNER), json={"brand_name": "Second", "treatment": "current", "expected_version": 1})

    assert fresh.status_code == 200 and fresh.json()["brand_name"] == "Second"


@pytest.mark.asyncio
async def test_revoked_member_loses_branding_access(client, branding_db):

    async with branding_db() as session, session.begin():
        member = await session.get(OrganizationMemberRow, {"organization_id": SHARED_ID, "user_id": ADMIN})

        member.status = "revoked"

    assert (await client.get(_url(), headers=_as(ADMIN))).status_code == 404


@pytest.mark.asyncio
async def test_existing_workspace_selection_still_works(client):

    # Branding is additive: listing and selection semantics are unchanged.

    listing = await client.get("/api/workspaces", headers=_as(OWNER))

    assert listing.status_code == 200

    assert [w["id"] for w in listing.json()["workspaces"]] == [SHARED_ID]

    selected = await client.post("/api/workspaces/select", headers=_as(OWNER), json={"workspace_id": SHARED_ID})

    assert selected.status_code == 200 and selected.json()["active_workspace_id"] == SHARED_ID


# --- review round 2: atomicity, DELETE conflict, real raster validation -----


@pytest.mark.asyncio
async def test_concurrent_editors_cannot_both_win_stale_write(client):
    """Two editors racing from the same version: exactly one wins, one gets 412."""

    await client.put(_url(), headers=_as(OWNER), json={"brand_name": "Base", "treatment": "current"})

    first, second = await asyncio.gather(
        client.put(_url(), headers=_as(OWNER), json={"brand_name": "A", "treatment": "current", "expected_version": 1}),
        client.put(_url(), headers=_as(ADMIN), json={"brand_name": "B", "treatment": "current", "expected_version": 1}),
        return_exceptions=False,
    )

    codes = sorted([first.status_code, second.status_code])

    assert codes == [200, 412], codes

    winner = first if first.status_code == 200 else second

    assert winner.json()["version"] == 2

    # The losing write left nothing behind.

    current = await client.get(_url(), headers=_as(OWNER))

    assert current.json()["version"] == 2

    assert current.json()["brand_name"] == winner.json()["brand_name"]


@pytest.mark.asyncio
async def test_concurrent_initial_insert_only_one_creates_the_row(client, branding_db):
    """Simultaneous first write races on the primary key, not on a read."""

    first, second = await asyncio.gather(
        client.put(_url(), headers=_as(OWNER), json={"brand_name": "A", "treatment": "current", "expected_version": 0}),
        client.put(_url(), headers=_as(ADMIN), json={"brand_name": "B", "treatment": "current", "expected_version": 0}),
    )

    assert sorted([first.status_code, second.status_code]) == [200, 412]

    async with branding_db() as session:
        row = await session.get(OrganizationBrandingRow, SHARED_ID)

        assert row.version == 1


@pytest.mark.asyncio
async def test_delete_takes_expected_version_as_query_param_and_412s_when_stale(client):

    await client.put(_url(), headers=_as(OWNER), json={"brand_name": "Momentum", "treatment": "paper"})

    stale = await client.delete(_url() + "?expected_version=0", headers=_as(OWNER))

    assert stale.status_code == 412

    fresh = await client.delete(_url() + "?expected_version=1", headers=_as(OWNER))

    assert fresh.status_code == 200

    assert fresh.json()["version"] == 2 and fresh.json()["brand_name"] is None


@pytest.mark.asyncio
async def test_reset_of_untouched_brand_still_advances_version(client, branding_db):
    """No row yet: reset creates the defaults row so the contract stays monotonic."""

    reset = await client.delete(_url() + "?expected_version=0", headers=_as(OWNER))

    assert reset.status_code == 200

    body = reset.json()

    assert body["version"] == 1 and body["brand_name"] is None and body["treatment"] == "current"

    async with branding_db() as session:
        assert (await session.get(OrganizationBrandingRow, SHARED_ID)) is not None

    # A write that still believes the brand was untouched is now rejected.

    assert (await client.put(_url(), headers=_as(OWNER), json={"brand_name": "X", "treatment": "current", "expected_version": 0})).status_code == 412


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("logo", "expected", "why"),
    [
        (_truncated_png(), 415, "valid PNG header, body cut short"),
        (_header_only_png(), 415, "PNG signature and IHDR only, no image data"),
        (_fake_webp(), 415, "fake WebP container"),
    ],
)
async def test_forged_or_truncated_rasters_are_rejected(client, branding_db, logo, expected, why):
    """A real decode is required; first bytes are never enough."""

    result = await client.put(_url(), headers=_as(OWNER), json={"logo": logo, "treatment": "current"})

    assert result.status_code == expected, f"{why}: got {result.status_code}"

    async with branding_db() as session:
        assert await session.get(OrganizationBrandingRow, SHARED_ID) is None


@pytest.mark.asyncio
async def test_real_jpeg_and_webp_are_accepted(client):
    """The decoder accepts genuine rasters of every declared type."""

    for data_uri in (_real("JPEG", "jpeg"), _real("WEBP", "webp")):
        result = await client.put(_url(), headers=_as(OWNER), json={"logo": data_uri, "treatment": "current"})

        assert result.status_code == 200, result.text


# --- review round 4: boundary edges -----------------------------------------


@pytest.mark.asyncio
async def test_decompression_bomb_is_413_not_500(client, branding_db):
    """Pillow's bomb guard fires inside open(), before our own dimension cap.

    DecompressionBombError derives from Exception, not OSError/ValueError, so
    it used to escape the decoder as a 500. The payload is 68 bytes: the huge
    numbers live only in the header, so nothing is allocated to prove this.
    """
    payload = _bomb_png()
    assert len(base64.b64decode(payload.split(",", 1)[1])) < 200, "the probe must stay tiny"
    result = await client.put(_url(), headers=_as(OWNER), json={"logo": payload, "treatment": "current"})
    assert result.status_code == 413, result.text
    async with branding_db() as session:
        assert await session.get(OrganizationBrandingRow, SHARED_ID) is None


@pytest.mark.asyncio
async def test_padded_brand_name_within_bounds_after_strip_is_accepted(client):
    """The contract is 1-120 after strip; raw length must not decide it."""
    core = "M" * 118
    padded = "   " + core + "   "  # 124 raw, 118 stripped
    assert len(padded) > 120 and len(padded.strip()) <= 120
    result = await client.put(_url(), headers=_as(OWNER), json={"brand_name": padded, "treatment": "current"})
    assert result.status_code == 200, result.text
    assert result.json()["brand_name"] == core


@pytest.mark.asyncio
async def test_brand_name_over_120_after_strip_is_still_rejected(client):
    """Tightening the pre-strip bound must not loosen the real limit."""
    result = await client.put(_url(), headers=_as(OWNER), json={"brand_name": "M" * 121, "treatment": "current"})
    assert result.status_code == 422


@pytest.mark.asyncio
async def test_non_editor_member_reads_but_cannot_write(client, branding_db):
    """An active member outside owner/admin: read yes, write and reset 403."""
    read = await client.get(_url(), headers=_as(VIEWER))
    assert read.status_code == 200
    assert read.json()["can_edit"] is False

    write = await client.put(_url(), headers=_as(VIEWER), json={"brand_name": "Nope", "treatment": "classic"})
    assert write.status_code == 403

    reset = await client.delete(_url() + "?expected_version=0", headers=_as(VIEWER))
    assert reset.status_code == 403

    async with branding_db() as session:
        assert await session.get(OrganizationBrandingRow, SHARED_ID) is None


@pytest.mark.asyncio
async def test_unavailable_persistence_is_503(client, monkeypatch):
    """No session factory is a bounded 503, not an unhandled error."""
    monkeypatch.setattr(workspaces, "get_session_factory", lambda: None)
    assert (await client.get(_url(), headers=_as(OWNER))).status_code == 503
    assert (await client.put(_url(), headers=_as(OWNER), json={"brand_name": "X", "treatment": "current"})).status_code == 503
    assert (await client.delete(_url() + "?expected_version=0", headers=_as(OWNER))).status_code == 503
