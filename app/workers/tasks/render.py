"""Render Celery tasks."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.constants import ErrorCode
from app.models.asset import Asset
from app.models.edit_plan import EditPlan
from app.models.job import Job
from app.models.render import Render
from app.models.video import Video
from app.workers.celery_app import celery_app

settings = get_settings()
sync_engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
SyncSession = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)


@celery_app.task(name="app.workers.tasks.render.run_render_job", bind=True, max_retries=2)
def run_render_job(self, job_id: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    with SyncSession() as session:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
        if not job:
            return {"status": "missing"}
        if job.status == "cancelled":
            return {"status": "cancelled", "job_id": job_id}

        render_id = (job.input_payload or {}).get("render_id")
        render = None
        if render_id:
            render = session.execute(
                select(Render).where(Render.id == render_id)
            ).scalar_one_or_none()

        edit_plan = None
        source_asset = None
        if render:
            edit_plan = session.execute(
                select(EditPlan).where(EditPlan.id == render.edit_plan_id)
            ).scalar_one_or_none()
            video = session.execute(
                select(Video).where(Video.id == render.source_video_id)
            ).scalar_one_or_none()
            if video:
                source_asset = session.execute(
                    select(Asset).where(Asset.id == video.original_asset_id)
                ).scalar_one_or_none()

        job.celery_task_id = self.request.id
        job.status = "processing"
        job.started_at = datetime.now(UTC)
        if render:
            render.status = "processing"
            render.job_id = job.id
        session.commit()

        try:
            if not render or not edit_plan or not source_asset:
                raise RuntimeError("Render context missing")

            async def _run() -> None:
                from app.services.render.service import complete_render_inline

                engine = create_async_engine(settings.database_url, pool_pre_ping=True)
                SessionLocal = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                try:
                    async with SessionLocal() as asession:
                        # Re-load entities in async session
                        a_job = (
                            await asession.execute(select(Job).where(Job.id == job_id))
                        ).scalar_one()
                        a_render = (
                            await asession.execute(
                                select(Render).where(Render.id == render.id)
                            )
                        ).scalar_one()
                        a_plan = (
                            await asession.execute(
                                select(EditPlan).where(EditPlan.id == edit_plan.id)
                            )
                        ).scalar_one()
                        a_asset = (
                            await asession.execute(
                                select(Asset).where(Asset.id == source_asset.id)
                            )
                        ).scalar_one()
                        await complete_render_inline(
                            asession,
                            job=a_job,
                            render=a_render,
                            edit_plan=a_plan,
                            source_asset=a_asset,
                            settings=settings,
                        )
                        await asession.commit()
                finally:
                    await engine.dispose()

            asyncio.run(_run())
            return {"status": "completed", "job_id": job_id}
        except Exception as exc:
            session.refresh(job)
            if render:
                session.refresh(render)
                render.status = "failed"
                render.error_code = ErrorCode.RENDER_FAILED.value
                render.error_message = str(exc)[:500]
            job.status = "failed"
            job.error_code = ErrorCode.RENDER_FAILED.value
            job.error_message = str(exc)[:500]
            job.completed_at = datetime.now(UTC)
            session.commit()
            raise self.retry(exc=exc, countdown=2**self.request.retries) from exc
