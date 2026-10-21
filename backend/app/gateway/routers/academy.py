"""AI Academy: Momentum staff training, plus each person's own progress.

Same gate as the team board (``require_momentum_staff``): the curriculum and
the progress routes answer 404 to anyone who isn't staff on Momentum's own
instance. Progress is always read and written for the caller's own id.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.gateway.academy_content import ACADEMY_MEDIA_NAMES, TRACKS, Lesson, lesson_ids
from app.gateway.authz import require_permission
from app.gateway.deps import get_academy_progress_repo, get_config
from app.gateway.momentum_internal import momentum_staff_only, require_momentum_staff
from deerflow.config.app_config import AppConfig
from deerflow.config.paths import get_paths

# Gate first (404 for anyone who isn't Momentum staff), and keep these
# routes out of the public OpenAPI schema.
router = APIRouter(prefix="/api/academy", tags=["academy"], dependencies=[Depends(momentum_staff_only)], include_in_schema=False)


class AcademyLessonResponse(BaseModel):
    id: str
    title: str
    minutes: int
    summary: str
    steps: list[str]
    try_it: str
    video_slot: str | None
    video_url: str | None
    video_poster_url: str | None = None
    video_captions_url: str | None = None
    video_transcript_url: str | None = None
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


def _media_path(filename: str) -> Path:
    root = (get_paths().base_dir / "academy-media").resolve()
    path = (root / filename).resolve()
    if filename not in ACADEMY_MEDIA_NAMES or not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=404, detail="Academy media not found")
    return path


def _published_media(lesson: Lesson) -> Lesson:
    stem = lesson["video_slot"]
    if stem is None:
        return lesson
    # Release stages the accepted set together; incomplete uploads stay out of the player.
    try:
        for extension in ("mp4", "jpg", "vtt", "txt"):
            _media_path(f"{stem}.{extension}")
    except HTTPException:
        return lesson
    return {
        **lesson,
        "video_url": f"/api/academy/media/{stem}.mp4",
        "video_poster_url": f"/api/academy/media/{stem}.jpg",
        "video_captions_url": f"/api/academy/media/{stem}.vtt",
        "video_transcript_url": f"/api/academy/media/{stem}.txt",
    }


@router.get("/media/{filename}", response_class=FileResponse)
@require_permission("academy", "read")
async def get_academy_media(filename: str, request: Request, config: AppConfig = Depends(get_config)) -> FileResponse:
    await require_momentum_staff(request, config)
    path = _media_path(filename)
    for extension in ("mp4", "jpg", "vtt", "txt"):
        _media_path(f"{Path(filename).stem}.{extension}")
    return FileResponse(path, headers={"Cache-Control": "private, no-store"})


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
            lessons=[AcademyLessonResponse(**_published_media(lesson), completed=lesson["id"] in done) for lesson in track["lessons"]],
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
