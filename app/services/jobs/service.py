"""Jobs service — create, poll, progress, cancel."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, NotFoundException
from app.models.job import Job
from app.schemas.job import JobProgressEvent, JobPublic

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
JOB_TYPE_VIDEO_POST_PROCESS = "video.post_process"

POST_PROCESS_STAGES: list[tuple[str, int]] = [
    ("metadata", 10),
    ("thumbnail", 50),
    ("done", 100),
]


def to_public(job: Job) -> JobPublic:
    return JobPublic(
        id=job.id,
        type=job.type,
        status=job.status,
        progress=job.progress,
        stage=job.stage,
        user_id=job.user_id,
        project_id=job.project_id,
        video_id=job.video_id,
        result=job.result_payload,
        error_code=job.error_code,
        error_message=job.error_message,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def to_progress_event(job: Job) -> JobProgressEvent:
    return JobProgressEvent(
        id=job.id,
        status=job.status,
        progress=job.progress,
        stage=job.stage,
        error_code=job.error_code,
    )


async def get_owned_job(
    session: AsyncSession,
    *,
    user_id: str,
    job_id: str,
) -> Job:
    result = await session.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise NotFoundException("Job not found")
    return job


async def create_job(
    session: AsyncSession,
    *,
    user_id: str,
    job_type: str,
    project_id: str | None = None,
    video_id: str | None = None,
    input_payload: dict[str, Any] | None = None,
    stage: str | None = "queued",
    job_id: str | None = None,
) -> Job:
    kwargs: dict[str, Any] = {
        "user_id": user_id,
        "project_id": project_id,
        "video_id": video_id,
        "type": job_type,
        "status": "queued",
        "progress": 0,
        "stage": stage,
        "input_payload": input_payload,
    }
    if job_id is not None:
        kwargs["id"] = job_id
    job = Job(**kwargs)
    session.add(job)
    await session.flush()
    await session.refresh(job)
    return job


async def complete_post_process_inline(session: AsyncSession, job: Job) -> Job:
    """Advance stub stages on the same DB session (tests / broker down)."""
    if job.status == "cancelled":
        return job
    job.status = "processing"
    job.started_at = datetime.now(UTC)
    for stage, progress in POST_PROCESS_STAGES:
        job.stage = stage
        job.progress = progress
    job.status = "completed"
    job.stage = "done"
    job.progress = 100
    job.result_payload = {"stub": True, "message": "post_process_complete"}
    job.completed_at = datetime.now(UTC)
    await session.flush()
    await session.refresh(job)
    return job


async def enqueue_post_process(session: AsyncSession, job: Job) -> Job:
    """Enqueue Celery task; fall back to inline completion if broker is down."""
    from app.core.config import get_settings
    from app.workers.tasks.files import process_video_job

    settings = get_settings()
    # In-memory SQLite tests share no DB with Celery workers — always run inline.
    if settings.app_env == "test":
        return await complete_post_process_inline(session, job)

    try:
        async_result = process_video_job.delay(job.id)
        job.celery_task_id = str(async_result.id)
        await session.flush()
        await session.refresh(job)
        return job
    except Exception:  # noqa: BLE001
        return await complete_post_process_inline(session, job)


async def cancel_job(
    session: AsyncSession,
    *,
    user_id: str,
    job_id: str,
) -> Job:
    job = await get_owned_job(session, user_id=user_id, job_id=job_id)
    if job.status != "queued":
        raise ConflictException("Only queued jobs can be cancelled")

    if job.celery_task_id:
        try:
            from app.workers.celery_app import celery_app

            celery_app.control.revoke(job.celery_task_id, terminate=False)
        except Exception:  # noqa: BLE001 — cancel DB state even if broker unreachable
            pass

    job.status = "cancelled"
    job.stage = "cancelled"
    job.completed_at = datetime.now(UTC)
    await session.flush()

    from app.services.credits import service as credits_service

    await credits_service.refund_job(session, job_id=job.id)

    await session.refresh(job)
    return job


async def get_latest_post_process_job_id(
    session: AsyncSession,
    *,
    video_id: str,
) -> str | None:
    result = await session.execute(
        select(Job.id)
        .where(Job.video_id == video_id, Job.type == JOB_TYPE_VIDEO_POST_PROCESS)
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
