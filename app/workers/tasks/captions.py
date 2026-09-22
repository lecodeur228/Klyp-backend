"""Caption generation Celery tasks."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.captions.build import build_cues
from app.core.config import get_settings
from app.core.constants import ErrorCode
from app.models.analysis import VideoAnalysis
from app.models.job import Job
from app.models.video_caption import VideoCaption
from app.services.captions.service import CAPTION_STAGES
from app.workers.celery_app import celery_app

settings = get_settings()
sync_engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
SyncSession = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)


@celery_app.task(
    name="app.workers.tasks.captions.generate_captions_job",
    bind=True,
    max_retries=2,
)
def generate_captions_job(self, job_id: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    with SyncSession() as session:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
        if not job:
            return {"status": "missing"}
        if job.status == "cancelled":
            return {"status": "cancelled", "job_id": job_id}

        captions_id = (job.input_payload or {}).get("captions_id")
        captions = None
        if captions_id:
            captions = session.execute(
                select(VideoCaption).where(VideoCaption.id == captions_id)
            ).scalar_one_or_none()
        if not captions and job.video_id:
            captions = session.execute(
                select(VideoCaption).where(VideoCaption.video_id == job.video_id)
            ).scalar_one_or_none()

        analysis = None
        if job.video_id:
            analysis = session.execute(
                select(VideoAnalysis).where(VideoAnalysis.video_id == job.video_id)
            ).scalar_one_or_none()

        job.celery_task_id = self.request.id
        job.status = "processing"
        job.started_at = datetime.now(UTC)
        if captions:
            captions.status = "processing"
            captions.job_id = job.id
        session.commit()

        try:
            for stage, progress in CAPTION_STAGES[:-1]:
                session.refresh(job)
                if job.status == "cancelled":
                    return {"status": "cancelled", "job_id": job_id}
                job.stage = stage
                job.progress = progress
                session.commit()

            if not captions or not analysis:
                raise RuntimeError("Captions context missing")

            style = captions.style if captions.style in ("minimal", "dynamic") else "minimal"
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
            session.commit()
            return {"status": "completed", "job_id": job_id}
        except Exception as exc:
            if captions:
                captions.status = "failed"
                captions.error_code = ErrorCode.JOB_FAILED.value
                captions.error_message = str(exc)[:500]
            job.status = "failed"
            job.error_code = ErrorCode.JOB_FAILED.value
            job.error_message = str(exc)[:500]
            job.completed_at = datetime.now(UTC)
            session.commit()
            raise self.retry(exc=exc, countdown=2**self.request.retries) from exc
