"""Captions service — generate from analysis, get, patch."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.captions.build import build_cues, validate_cues_monotonic
from app.core.config import Settings, get_settings
from app.core.constants import ErrorCode
from app.core.exceptions import ConflictException, NotFoundException, ValidationException
from app.models.analysis import VideoAnalysis
from app.models.edit_plan import EditPlan
from app.models.job import Job
from app.models.video_caption import VideoCaption
from app.schemas.captions import (
    CaptionsPatchRequest,
    CaptionsPublic,
    CaptionsStarted,
)
from app.services.jobs import service as jobs_service
from app.services.videos import service as videos_service

JOB_TYPE_VIDEO_CAPTIONS = "video.captions"
CaptionStyle = Literal["minimal", "dynamic"]

CAPTION_STAGES: list[tuple[str, int]] = [
    ("loading", 20),
    ("building", 70),
    ("done", 100),
]


def to_public(row: VideoCaption) -> CaptionsPublic:
    return CaptionsPublic(
        id=row.id,
        video_id=row.video_id,
        job_id=row.job_id,
        status=row.status,
        style=row.style,
        language=row.language,
        cues=list(row.cues or []),
        error_code=row.error_code,
        error_message=row.error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _get_by_video(
    session: AsyncSession, *, video_id: str
) -> VideoCaption | None:
    result = await session.execute(
        select(VideoCaption).where(VideoCaption.video_id == video_id)
    )
    return result.scalar_one_or_none()


async def _default_style(
    session: AsyncSession, *, project_id: str, requested: str | None
) -> CaptionStyle:
    if requested in ("minimal", "dynamic"):
        return requested  # type: ignore[return-value]
    edit_plan = (
        await session.execute(select(EditPlan).where(EditPlan.project_id == project_id))
    ).scalar_one_or_none()
    if edit_plan and isinstance(edit_plan.plan, dict):
        captions = edit_plan.plan.get("captions") or {}
        style = captions.get("style")
        if style in ("minimal", "dynamic"):
            return style
    return "minimal"


async def get_captions(
    session: AsyncSession,
    *,
    user_id: str,
    video_id: str,
) -> CaptionsPublic:
    await videos_service.get_owned_video(session, user_id=user_id, video_id=video_id)
    row = await _get_by_video(session, video_id=video_id)
    if not row:
        raise NotFoundException("Captions not found")
    return to_public(row)


async def start_captions(
    session: AsyncSession,
    *,
    user_id: str,
    video_id: str,
    style: str | None = None,
    settings: Settings | None = None,
) -> CaptionsStarted:
    settings = settings or get_settings()
    video, _asset = await videos_service.get_owned_video(
        session, user_id=user_id, video_id=video_id
    )

    analysis = (
        await session.execute(
            select(VideoAnalysis).where(VideoAnalysis.video_id == video.id)
        )
    ).scalar_one_or_none()
    if not analysis or analysis.status != "ready":
        raise ConflictException("Analysis must be ready before generating captions")

    row = await _get_by_video(session, video_id=video.id)
    if row and row.status == "processing":
        raise ConflictException("Captions generation already in progress")

    resolved_style = await _default_style(
        session, project_id=video.project_id, requested=style
    )

    if row is None:
        row = VideoCaption(
            video_id=video.id,
            status="pending",
            style=resolved_style,
            language=analysis.language,
            cues=[],
        )
        session.add(row)
        await session.flush()
    else:
        row.style = resolved_style
        row.language = analysis.language
        row.status = "pending"
        row.error_code = None
        row.error_message = None

    job = await jobs_service.create_job(
        session,
        user_id=user_id,
        job_type=JOB_TYPE_VIDEO_CAPTIONS,
        project_id=video.project_id,
        video_id=video.id,
        input_payload={
            "captions_id": row.id,
            "style": resolved_style,
            "analysis_id": analysis.id,
        },
        stage="queued",
    )
    row.job_id = job.id
    await session.flush()

    await enqueue_captions(
        session, job=job, captions=row, analysis=analysis, settings=settings
    )

    return CaptionsStarted(
        captions_id=row.id,
        job_id=job.id,
        status=row.status,
    )


async def patch_captions(
    session: AsyncSession,
    *,
    user_id: str,
    video_id: str,
    patch: CaptionsPatchRequest,
) -> CaptionsPublic:
    await videos_service.get_owned_video(session, user_id=user_id, video_id=video_id)
    row = await _get_by_video(session, video_id=video_id)
    if not row:
        raise NotFoundException("Captions not found")

    if patch.style is not None:
        row.style = patch.style
    if patch.cues is not None:
        cues_data: list[dict[str, Any]] = [
            c.model_dump(mode="json") for c in patch.cues
        ]
        errors = validate_cues_monotonic(cues_data)
        if errors:
            raise ValidationException("Invalid caption cues", errors=errors)
        row.cues = cues_data
        row.status = "ready"

    await session.flush()
    await session.refresh(row)
    return to_public(row)


async def complete_captions_inline(
    session: AsyncSession,
    *,
    job: Job,
    captions: VideoCaption,
    analysis: VideoAnalysis,
) -> VideoCaption:
    if job.status == "cancelled":
        captions.status = "failed"
        captions.error_code = ErrorCode.JOB_FAILED.value
        captions.error_message = "Job cancelled"
        await session.flush()
        return captions

    job.status = "processing"
    job.started_at = datetime.now(UTC)
    captions.status = "processing"

    for stage, progress in CAPTION_STAGES[:-1]:
        job.stage = stage
        job.progress = progress

    style: CaptionStyle = (
        captions.style if captions.style in ("minimal", "dynamic") else "minimal"
    )
    cues = build_cues(list(analysis.segments or []), style=style)

    captions.cues = cues
    captions.language = analysis.language
    captions.status = "ready"
    captions.error_code = None
    captions.error_message = None
    captions.job_id = job.id

    job.stage = "done"
    job.progress = 100
    job.status = "completed"
    job.result_payload = {
        "captions_id": captions.id,
        "cue_count": len(cues),
        "style": style,
    }
    job.completed_at = datetime.now(UTC)

    await session.flush()
    await session.refresh(captions)
    await session.refresh(job)
    return captions


async def enqueue_captions(
    session: AsyncSession,
    *,
    job: Job,
    captions: VideoCaption,
    analysis: VideoAnalysis,
    settings: Settings,
) -> Job:
    if settings.app_env == "test":
        await complete_captions_inline(
            session, job=job, captions=captions, analysis=analysis
        )
        return job

    from app.workers.tasks.captions import generate_captions_job

    try:
        async_result = generate_captions_job.delay(job.id)
        job.celery_task_id = str(async_result.id)
        captions.status = "processing"
        await session.flush()
        await session.refresh(job)
        return job
    except Exception:  # noqa: BLE001
        await complete_captions_inline(
            session, job=job, captions=captions, analysis=analysis
        )
        return job
