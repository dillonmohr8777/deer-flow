"""Shared workspace branding: member read, owner/admin update and reset.

Membership is resolved with ``active_organization_for_user()``, so the actor's
own membership row is the authorization input. The workspace storage principal
is a storage bucket and is never treated as an actor identity — knowing a
workspace id grants nothing without an active membership row.

Branding is a shared-workspace concept only. Private organizations keep their
existing behavior and answer 404 here.

No team motion setting exists by design: reduced-motion stays a per-user
accessibility control and a workspace cannot override it.
"""

from __future__ import annotations

import base64
from binascii import Error as BinasciiError
from datetime import UTC, datetime
from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, BeforeValidator, Field
from sqlalchemy import insert, update
from sqlalchemy.exc import IntegrityError

from app.gateway.routers.workspaces import _session_actor, _session_factory
from deerflow.persistence.organizations.branding import (
    DEFAULT_TREATMENT,
    WORKSPACE_TREATMENTS,
    OrganizationBrandingRow,
)
from deerflow.persistence.organizations.resolution import active_organization_for_user

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

#: Mirrors MAX_PLUGIN_ICON_DATA_LENGTH in frontend/src/core/mcp/icon.ts, which
#: is the boundary the existing client-side raster helper already enforces.
MAX_BRAND_LOGO_DATA_LENGTH = 100_000
MAX_BRAND_LOGO_DECODED_BYTES = 65_536
MAX_BRAND_LOGO_DIMENSION = 512
_OVERSIZED_LOGO_DETAIL = f"Logo must be at most {MAX_BRAND_LOGO_DIMENSION}x{MAX_BRAND_LOGO_DIMENSION} pixels"
MAX_BRAND_NAME_LENGTH = 120
#: Raw bound applied before stripping, so a whitespace-padded name that is
#: within the documented 1-120 after strip is still accepted, while an
#: unbounded payload is still refused.
MAX_BRAND_NAME_RAW_LENGTH = 4_096

_LOGO_PREFIXES = {
    "data:image/png;base64,": "png",
    "data:image/jpeg;base64,": "jpeg",
    "data:image/webp;base64,": "webp",
}


def _strip_brand_name(value: object) -> object:
    """Strip before Pydantic applies ``max_length``.

    The contract is "1-120 characters after strip". Applying ``max_length`` to
    the raw string rejected a padded value whose stripped form was in range, so
    the strip has to happen first. A raw ceiling still bounds the input.
    """
    if not isinstance(value, str):
        return value
    if len(value) > MAX_BRAND_NAME_RAW_LENGTH:
        raise ValueError("Brand name is too long")
    return value.strip()


#: Stripped by a before-validator, so the 120 bound below measures the stripped
#: value exactly as the contract documents.
BrandName = Annotated[str | None, BeforeValidator(_strip_brand_name)]

#: Same role tuple the invitation router gates shared-workspace writes on.
_EDIT_ROLES = ("owner", "admin")


class WorkspaceBrandingResponse(BaseModel):
    workspace_id: str
    brand_name: str | None = None
    workspace_name: str
    logo: str | None = None
    treatment: str = DEFAULT_TREATMENT
    version: int = 0
    updated_at: datetime | None = None
    can_edit: bool = False


class WorkspaceBrandingUpdateRequest(BaseModel):
    brand_name: BrandName = Field(default=None, max_length=MAX_BRAND_NAME_LENGTH)
    # Bounded here as well as in _validated_logo so an oversized body is
    # rejected by validation before it is decoded.
    logo: str | None = Field(default=None, max_length=MAX_BRAND_LOGO_DATA_LENGTH + 1)
    treatment: str = Field(default=DEFAULT_TREATMENT, max_length=16)
    expected_version: int | None = None


def _decode_raster(kind: str, blob: bytes) -> tuple[int, int]:
    """Prove the payload is a decodable raster of the declared type.

    Uses Pillow, already resolved in backend/uv.lock (12.3.0, via python-pptx)
    and therefore present in the built image. Nothing is installed for this.

    Order matters: format and dimensions come from the parsed header and the
    size cap is enforced BEFORE load(), so an oversized image is rejected
    without being decoded. load() then forces a full decode, so a truncated or
    forged payload whose first bytes look correct still fails. The server never
    accepts a raster on magic bytes alone.
    """
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:  # pragma: no cover - fail closed, never header-sniff
        raise HTTPException(status_code=503, detail="Image validation is unavailable") from None

    expected_format = {"png": "PNG", "jpeg": "JPEG", "webp": "WEBP"}[kind]
    try:
        probe = Image.open(BytesIO(blob))
        image_format, (width, height) = probe.format, probe.size
    except Image.DecompressionBombError:
        # Pillow's own guard fires inside open(), before our dimension cap can
        # run, and DecompressionBombError derives from Exception rather than
        # OSError/ValueError -- so without this it escapes as a 500. A tiny
        # header can declare enormous dimensions, so nothing is allocated here.
        raise HTTPException(status_code=413, detail=_OVERSIZED_LOGO_DETAIL) from None
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(status_code=415, detail="Logo is not a readable image") from None

    if image_format != expected_format:
        raise HTTPException(status_code=415, detail="Logo content does not match its declared image type")
    if not width or not height or width > MAX_BRAND_LOGO_DIMENSION or height > MAX_BRAND_LOGO_DIMENSION:
        raise HTTPException(status_code=413, detail=_OVERSIZED_LOGO_DETAIL)
    try:
        Image.open(BytesIO(blob)).load()
    except Image.DecompressionBombError:
        raise HTTPException(status_code=413, detail=_OVERSIZED_LOGO_DETAIL) from None
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(status_code=415, detail="Logo image data is incomplete or corrupt") from None
    return width, height


def _validated_logo(value: str | None) -> str | None:
    """Accept only a bounded, self-contained raster data URI.

    SVG and any remote reference are rejected outright, and the declared type is
    never trusted: the decoded magic bytes must agree with it.
    """
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if len(candidate) > MAX_BRAND_LOGO_DATA_LENGTH:
        raise HTTPException(status_code=413, detail="Logo exceeds the maximum encoded size")
    kind = next((k for prefix, k in _LOGO_PREFIXES.items() if candidate.startswith(prefix)), None)
    if kind is None:
        raise HTTPException(status_code=415, detail="Logo must be a base64 PNG, JPEG or WebP data URI")
    try:
        blob = base64.b64decode(candidate.split(",", 1)[1], validate=True)
    except (BinasciiError, ValueError, IndexError):
        raise HTTPException(status_code=415, detail="Logo payload is not valid base64") from None
    if not blob:
        raise HTTPException(status_code=415, detail="Logo payload is empty")
    if len(blob) > MAX_BRAND_LOGO_DECODED_BYTES:
        raise HTTPException(status_code=413, detail="Logo exceeds the maximum decoded size")
    _decode_raster(kind, blob)
    return candidate


def _validated_brand_name(value: str | None) -> str | None:
    if value is None:
        return None
    name = value.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Brand name must contain a non-whitespace character")
    if len(name) > MAX_BRAND_NAME_LENGTH:
        raise HTTPException(status_code=422, detail="Brand name is too long")
    return name


def _validated_treatment(value: str) -> str:
    if value not in WORKSPACE_TREATMENTS:
        raise HTTPException(status_code=409, detail="Treatment must be one of " + ", ".join(WORKSPACE_TREATMENTS))
    return value


async def _shared_membership(session, actor_id: str, workspace_id: str):
    """Resolve an active shared-workspace membership, or 404.

    404 rather than 403 for a non-member: knowing an id must not confirm the
    workspace exists. A private organization is 404 here too, because branding
    is a shared-workspace concept only.
    """
    active = await active_organization_for_user(session, actor_id, workspace_id)
    if active is None or active.storage_user_id is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return active


def _response(active, row, *, can_edit: bool) -> WorkspaceBrandingResponse:
    return WorkspaceBrandingResponse(
        workspace_id=active.id,
        brand_name=row.brand_name if row is not None else None,
        workspace_name=active.name,
        logo=row.logo_data_uri if row is not None else None,
        treatment=row.treatment if row is not None else DEFAULT_TREATMENT,
        version=row.version if row is not None else 0,
        updated_at=row.updated_at if row is not None else None,
        can_edit=can_edit,
    )


def _require_editor(active):
    if active.role not in _EDIT_ROLES:
        raise HTTPException(status_code=403, detail="Workspace owner or admin permission required")


@router.get("/{workspace_id}/branding", response_model=WorkspaceBrandingResponse)
async def get_workspace_branding(workspace_id: str, request: Request) -> WorkspaceBrandingResponse:
    actor = _session_actor(request)
    async with _session_factory()() as session:
        active = await _shared_membership(session, str(actor.id), workspace_id)
        row = await session.get(OrganizationBrandingRow, active.id)
        return _response(active, row, can_edit=active.role in _EDIT_ROLES)


_STALE = "Workspace branding changed since it was opened"


async def _apply_branding(session, organization_id, expected, *, brand_name, logo, treatment, actor_id):
    """Write branding under compare-and-set. Returns the stored row.

    The version check and the write are ONE statement, so two editors that both
    read the same version cannot both succeed: the loser's UPDATE matches no row
    and rowcount is 0. Creating the first row races on the primary key instead,
    so a simultaneous initial insert raises IntegrityError. Both are 412, and
    both work on SQLite and PostgreSQL without a backend-specific lock.
    """
    now = datetime.now(UTC)
    values = {
        "brand_name": brand_name,
        "logo_data_uri": logo,
        "treatment": treatment,
        "updated_by": actor_id,
        "updated_at": now,
    }
    if expected == 0:
        try:
            await session.execute(insert(OrganizationBrandingRow).values(organization_id=organization_id, version=1, created_at=now, **values))
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(status_code=412, detail=_STALE) from None
    else:
        result = await session.execute(
            update(OrganizationBrandingRow)
            .where(
                OrganizationBrandingRow.organization_id == organization_id,
                OrganizationBrandingRow.version == expected,
            )
            .values(version=expected + 1, **values)
        )
        await session.commit()
        if result.rowcount != 1:
            raise HTTPException(status_code=412, detail=_STALE)
    return await session.get(OrganizationBrandingRow, organization_id)


async def _resolve_expected(session, organization_id, supplied):
    """Use the caller's expected version, or fall back to the current one.

    Falling back keeps the write atomic — only the choice of compare operand is
    server-side. Retained for API compatibility; the frontend always supplies it.
    """
    if supplied is not None:
        return supplied
    row = await session.get(OrganizationBrandingRow, organization_id)
    return row.version if row is not None else 0


@router.put("/{workspace_id}/branding", response_model=WorkspaceBrandingResponse)
async def update_workspace_branding(
    workspace_id: str,
    body: WorkspaceBrandingUpdateRequest,
    request: Request,
) -> WorkspaceBrandingResponse:
    actor = _session_actor(request)
    actor_id = str(actor.id)
    async with _session_factory()() as session:
        active = await _shared_membership(session, actor_id, workspace_id)
        _require_editor(active)
        # Validate before any write so a rejected payload never bumps the version.
        brand_name = _validated_brand_name(body.brand_name)
        logo = _validated_logo(body.logo)
        treatment = _validated_treatment(body.treatment)
        expected = await _resolve_expected(session, active.id, body.expected_version)
        row = await _apply_branding(session, active.id, expected, brand_name=brand_name, logo=logo, treatment=treatment, actor_id=actor_id)
        return _response(active, row, can_edit=True)


@router.delete("/{workspace_id}/branding", response_model=WorkspaceBrandingResponse)
async def reset_workspace_branding(
    workspace_id: str,
    request: Request,
    expected_version: int | None = Query(default=None, ge=0),
) -> WorkspaceBrandingResponse:
    """Reset to defaults.

    expected_version is a query parameter because DELETE carries no body. A
    reset of an untouched workspace still participates in the version contract:
    with no row yet, this creates the defaults row at version 1 so a later stale
    write is still rejected.
    """
    actor = _session_actor(request)
    actor_id = str(actor.id)
    async with _session_factory()() as session:
        active = await _shared_membership(session, actor_id, workspace_id)
        _require_editor(active)
        expected = await _resolve_expected(session, active.id, expected_version)
        row = await _apply_branding(session, active.id, expected, brand_name=None, logo=None, treatment=DEFAULT_TREATMENT, actor_id=actor_id)
        return _response(active, row, can_edit=True)
