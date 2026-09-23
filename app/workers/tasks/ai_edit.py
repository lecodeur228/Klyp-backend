"""AI Edit Celery tasks."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.constants import ErrorCode
from app.editplan.validation import ensure_valid_edit_plan
from app.models.analysis import VideoAnalysis
from app.models.asset import Asset
from app.models.edit_plan import EditPlan
from app.models.job import Job
from app.models.video import Video
from app.pipeline.enrich import enrich_edit_plan
from app.services.editplan.service import (
    AI_EDIT_STAGES,
    build_fake_edit_plan,
    generate_edit_plan_document,
)
from app.workers.celery_app import celery_app

settings = get_settings()
sync_engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
SyncSession = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)


def _generate_document_sync(
    *,
    user_id: str,
    video_id: str,
    prompt: str,
    duration: float,
    analysis: VideoAnalysis,
    attachments: list | None = None,
) -> object:
    from app.schemas.editplan import AiEditAttachment

    atts: list[AiEditAttachment] = []
    for raw in attachments or []:
        if isinstance(raw, dict):
            try:
                atts.append(AiEditAttachment.model_validate(raw))
            except Exception:  # noqa: BLE001
                continue

    if settings.ai_provider == "fake":
        document = build_fake_edit_plan(
            source_video_id=video_id,
            duration=duration,
            vad_segments=list(analysis.vad_segments or []),
            prompt=prompt,
            attachments=atts,
        )
        document = ensure_valid_edit_plan(document, duration=duration)
        return enrich_edit_plan(
            plan=document,
            duration=duration,
            analysis_segments=list(analysis.segments or []),
            global_subject=(prompt or "")[:120] or None,
            art_direction="vibe-edit consistent palette",
            needs_review=False,
            dry_run=False,
        )

    async def _run():
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with SessionLocal() as asession:
                return await generate_edit_plan_document(
                    asession,
                    user_id=user_id,
                    video_id=video_id,
                    prompt=prompt,
                    duration=duration,
                    analysis=analysis,
                    settings=settings,
                    attachments=atts,
                )
        finally:
            await engine.dispose()

    return asyncio.run(_run())


@celery_app.task(name="app.workers.tasks.ai_edit.run_ai_edit_job", bind=True, max_retries=2)
def run_ai_edit_job(self, job_id: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    with SyncSession() as session:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
        if not job:
            return {"status": "missing"}
        if job.status == "cancelled":
            return {"status": "cancelled", "job_id": job_id}

        edit_plan_id = (job.input_payload or {}).get("edit_plan_id")
        prompt = (job.input_payload or {}).get("prompt", "")
        attachments = (job.input_payload or {}).get("attachments") or []
        edit_plan = None
        if edit_plan_id:
            edit_plan = session.execute(
                select(EditPlan).where(EditPlan.id == edit_plan_id)
            ).scalar_one_or_none()

        analysis = None
        asset = None
        if job.video_id:
            video = session.execute(
                select(Video).where(Video.id == job.video_id)
            ).scalar_one_or_none()
            if video:
                asset = session.execute(
                    select(Asset).where(Asset.id == video.original_asset_id)
                ).scalar_one_or_none()
                analysis = session.execute(
                    select(VideoAnalysis).where(VideoAnalysis.video_id == video.id)
                ).scalar_one_or_none()

        job.celery_task_id = self.request.id
        job.status = "processing"
        job.started_at = datetime.now(UTC)
        if edit_plan:
            edit_plan.status = "draft"
            edit_plan.job_id = job.id
        session.commit()

        try:
            for stage, progress in AI_EDIT_STAGES[:-1]:
                session.refresh(job)
                if job.status == "cancelled":
                    return {"status": "cancelled", "job_id": job_id}
                job.stage = stage
                job.progress = progress
                session.commit()

            if not edit_plan or not asset or not analysis:
                raise RuntimeError("EditPlan context missing")

            duration = float(asset.duration) if asset.duration else 30.0
            document = _generate_document_sync(
                user_id=job.user_id,
                video_id=edit_plan.source_video_id,
                prompt=prompt,
                duration=duration,
                analysis=analysis,
                attachments=attachments if isinstance(attachments, list) else [],
            )

            edit_plan.plan = document.model_dump(mode="json")  # type: ignore[union-attr]
            edit_plan.version = max(1, edit_plan.version + 1)
            edit_plan.prompt = prompt
            edit_plan.status = "ready"
            edit_plan.job_id = job.id

            job.stage = "done"
            job.progress = 100
            job.status = "completed"
            job.result_payload = {
                "edit_plan_id": edit_plan.id,
                "version": edit_plan.version,
            }
            job.completed_at = datetime.now(UTC)
            session.commit()
            return {"status": "completed", "job_id": job_id}
        except Exception as exc:
            if edit_plan:
                edit_plan.status = "failed"
            job.status = "failed"
            job.error_code = ErrorCode.JOB_FAILED.value
            job.error_message = str(exc)[:500]
            job.completed_at = datetime.now(UTC)
            session.commit()
            raise self.retry(exc=exc, countdown=2**self.request.retries) from exc
