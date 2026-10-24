"""Browser-only opaque Composio connection attempts; never expose auth links."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict

from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.deps import get_current_user_from_request
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.composio_sessions import ComposioSessionError, ConnectManager, composio_browser_origin

router = APIRouter(prefix="/api/integrations", tags=["integrations"])
logger = logging.getLogger(__name__)


class ConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    toolkit: str


class ConnectResponse(BaseModel):
    handle: str
    toolkit: str
    expires_at: str


def _failure(error):
    code = str(error)
    status = 404 if code in {"connect_disabled", "connect_attempt_not_found"} else 403 if code in {"composio_origin_denied", "composio_actor_denied", "connect_nonce_denied"} else 409
    return HTTPException(status, code)


@asynccontextmanager
async def _manager(request):
    await get_current_user_from_request(request)
    if getattr(request.state, "auth_source", None) != AUTH_SOURCE_SESSION:
        raise HTTPException(403, "An authenticated browser session is required")
    try:
        with composio_browser_origin():
            config = await asyncio.to_thread(ExtensionsConfig.from_file)
            yield ConnectManager(config)
    except ComposioSessionError as error:
        raise _failure(error) from None
    except HTTPException:
        raise
    except Exception as error:
        logger.warning("Composio connect boundary failed (%s)", type(error).__name__)
        raise HTTPException(503, "connect_backend_unavailable") from None


@router.post("/connect", response_model=ConnectResponse)
async def connect(body: ConnectRequest, request: Request):
    async with _manager(request) as manager:
        return await manager.create(body.toolkit)


@router.get("/connect/{handle}/open")
async def open_connection(handle: str, request: Request):
    async with _manager(request) as manager:
        target, nonce = await manager.open(handle)
        response = RedirectResponse(target, status_code=302)
        response.set_cookie("momo_connect_" + handle, nonce, max_age=manager.config.composio_me.connect.ttl_seconds, secure=True, httponly=True, samesite="lax", path="/api/integrations/callback")
        return response


@router.get("/callback")
async def callback(request: Request):
    expected = {"handle", "connected_account_id", "status"}
    if set(request.query_params) != expected or any(len(request.query_params.getlist(key)) != 1 for key in expected) or request.query_params["status"] not in {"success", "failed"}:
        raise HTTPException(400, "Invalid connection callback")
    handle = request.query_params["handle"]
    async with _manager(request) as manager:
        value = await manager.callback(handle, request.cookies.get("momo_connect_" + handle), request.query_params["connected_account_id"])
        if value["state"] == "complete":
            return value["reply"]
        if not await manager.claim_dispatch(value):
            raise HTTPException(409, "Connection completion is already claimed")
        reply = {"handle": handle, "toolkit": value["toolkit"], "status": "connected", "retry": {"state": "not_requested"}}
        if value.get("intent"):
            from app.gateway.routers.thread_runs import complete_composio_connection

            try:
                reply["retry"] = await complete_composio_connection(request, value)
            except Exception as error:
                logger.warning("Composio retry held (%s)", type(error).__name__)
                reply["retry"] = {"state": "held", "reason": "retry_admission_unavailable"}
        await manager.settle_dispatch(value, reply)
        return reply


@router.get("/status")
async def status(request: Request):
    async with _manager(request) as manager:
        try:
            return {"toolkits": await manager.status()}
        except ComposioSessionError as error:
            if str(error) not in {"connect_disabled", "legacy_connection_managed_separately"}:
                raise
            return {"toolkits": [{"toolkit": toolkit, "connected": False, "connectable": False, "reason": str(error)} for toolkit in manager.config.composio_me.toolkits]}
