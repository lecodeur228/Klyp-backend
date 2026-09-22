"""File / video processing Celery tasks."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.constants import ErrorCode
from app.models.job import Job
from app.services.jobs.service import POST_PROCESS_STAGES
from app.workers.celery_app import celery_app

settings = get_settings()
sync_engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
SyncSession = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)


@celery_app.task(name="app.workers.tasks.files.process_video_job", bind=True, max_retries=2)
def process_video_job(self, job_id: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    with SyncSession() as session:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
        if not job:
            return {"status": "missing"}
        if job.status == "cancelled":
            return {"status": "cancelled", "job_id": job_id}

        job.celery_task_id = self.request.id
        job.status = "processing"
        job.started_at = datetime.now(UTC)
        session.commit()

        try:
            for stage, progress in POST_PROCESS_STAGES:
                session.refresh(job)
                if job.status == "cancelled":
                    return {"status": "cancelled", "job_id": job_id}
                job.stage = stage
                job.progress = progress
                session.commit()

            job.status = "completed"
            job.stage = "done"
            job.progress = 100
            job.result_payload = {"stub": True, "message": "post_process_complete"}
            job.completed_at = datetime.now(UTC)
            session.commit()
            return {"status": "completed", "job_id": job_id}
        except Exception as exc:
            job.status = "failed"
            job.error_code = ErrorCode.JOB_FAILED.value
            job.error_message = str(exc)[:500]
            job.completed_at = datetime.now(UTC)
            session.commit()
            raise self.retry(exc=exc, countdown=2**self.request.retries) from exc


@celery_app.task(name="app.workers.tasks.files.process_file")
def process_file(file_path: str) -> dict[str, str]:
    """Legacy stub kept for route compatibility."""
    return {"status": "processed", "path": file_path}
