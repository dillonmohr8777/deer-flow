"""Owner-only MomoBot Agent Room message board."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import get_agent_room_repo, get_config, get_current_user_from_request, is_admin_user
from deerflow.config.app_config import AppConfig


async def private_owner_only(request: Request, config: AppConfig = Depends(get_config)) -> None:
    """Hide this surface unless private Desk is enabled for a system admin."""
    if config.private_workspace.enabled is not True or not await is_admin_user(request):
        raise HTTPException(status_code=404, detail="Not found")


router = APIRouter(
    prefix="/api/agent-room",
    tags=["agent-room"],
    dependencies=[Depends(private_owner_only)],
    include_in_schema=False,
)


class AgentRoomMessageResponse(BaseModel):
    id: str
    user_id: str
    author_kind: str
    agent_id: str | None = None
    agent_role: str = ""
    message_type: str
    body: str
    run_id: str | None = None
    created_at: str


class AgentRoomMessageListResponse(BaseModel):
    messages: list[AgentRoomMessageResponse]


class OwnerMessageRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)
    message_type: Literal["instruction", "note"] = "instruction"


def _check_expected_owner(request: Request, owner: str) -> None:
    """Fence a stale browser identity before any private repository read/write."""
    expected = request.headers.get("X-Expected-User-Id")
    if expected is not None and expected != owner:
        raise HTTPException(409, "The signed-in account changed; reload this page")


@router.get("/messages", response_model=AgentRoomMessageListResponse)
@require_permission("threads", "read")
async def list_messages(
    request: Request,
    limit: int = Query(default=100, ge=1, le=200),
) -> AgentRoomMessageListResponse:
    user = await get_current_user_from_request(request)
    _check_expected_owner(request, str(user.id))
    rows = await get_agent_room_repo(request).list_messages(user_id=str(user.id), limit=limit)
    return AgentRoomMessageListResponse(messages=[AgentRoomMessageResponse(**row) for row in rows])


@router.post("/messages", response_model=AgentRoomMessageResponse, status_code=201)
@require_permission("threads", "write")
async def post_owner_message(body: OwnerMessageRequest, request: Request) -> AgentRoomMessageResponse:
    user = await get_current_user_from_request(request)
    _check_expected_owner(request, str(user.id))
    text = body.body.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Message is empty")
    row = await get_agent_room_repo(request).add_message(
        user_id=str(user.id),
        author_kind="owner",
        body=text,
        message_type=body.message_type,
    )
    return AgentRoomMessageResponse(**row)
