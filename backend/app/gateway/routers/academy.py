"""AI Academy: Momentum staff training, plus each person's own progress.

Same gate as the team board (``require_momentum_staff``): the curriculum and
the progress routes answer 404 to anyone who isn't staff on Momentum's own
instance. Progress is always read and written for the caller's own id.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.gateway.academy_content import TRACKS, lesson_ids
from app.gateway.authz import require_permission
from app.gateway.deps import get_academy_progress_repo, get_config
from app.gateway.momentum_internal import require_momentum_staff
from deerflow.config.app_config import AppConfig

router = APIRouter(prefix="/api/academy", tags=["academy"])


class AcademyLessonResponse(BaseModel):
    id: str
    title: str
    minutes: int
    summary: str
    steps: list[str]
    try_it: str
    video_slot: str | None
    video_url: str | None
    completed: bool


class AcademyTrackResponse(BaseModel):
    id: str
    title: str
    summary: str
    lessons: list[AcademyLessonResponse]


class AcademyResponse(BaseModel):
    tracks: list[AcademyTrackResponse]
    completed_count: int
    lesson_count: int


class AcademyProgressRequest(BaseModel):
    completed: bool


@router.get("", response_model=AcademyResponse)
@require_permission("academy", "read")
async def get_academy(request: Request, config: AppConfig = Depends(get_config)) -> AcademyResponse:
    organization_id, user_id, _ = await require_momentum_staff(request, config)
    known = lesson_ids()
    # Drop progress for lessons that no longer exist so the count stays honest.
    done = await get_academy_progress_repo(request).completed_lessons(organization_id=organization_id, user_id=user_id) & known
    tracks = [
        AcademyTrackResponse(
            id=track["id"],
            title=track["title"],
            summary=track["summary"],
            lessons=[AcademyLessonResponse(**lesson, completed=lesson["id"] in done) for lesson in track["lessons"]],
        )
        for track in TRACKS
    ]
    return AcademyResponse(tracks=tracks, completed_count=len(done), lesson_count=len(known))


@router.put("/lessons/{lesson_id}/progress", status_code=204, response_class=Response)
@require_permission("academy", "write")
async def set_lesson_progress(lesson_id: str, body: AcademyProgressRequest, request: Request, config: AppConfig = Depends(get_config)) -> Response:
    organization_id, user_id, _ = await require_momentum_staff(request, config)
    if lesson_id not in lesson_ids():
        raise HTTPException(status_code=404, detail="Lesson not found")
    await get_academy_progress_repo(request).set_completed(organization_id=organization_id, user_id=user_id, lesson_id=lesson_id, completed=body.completed)
    return Response(status_code=204)
