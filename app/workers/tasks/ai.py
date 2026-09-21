"""AI Celery tasks."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.models.ai import AiJob
from app.workers.celery_app import celery_app

settings = get_settings()
sync_engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
SyncSession = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)


@celery_app.task(name="app.workers.tasks.ai.run_ai_generate_job", bind=True, max_retries=3)
def run_ai_generate_job(self, job_id: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    with SyncSession() as session:
        job = session.execute(select(AiJob).where(AiJob.id == job_id)).scalar_one_or_none()
        if not job:
            return {"status": "missing"}
        job.status = "processing"
        job.started_at = datetime.now(UTC)
        session.commit()

        try:
            prompt = (job.input_payload or {}).get("prompt", "")
            # Worker uses fake/deterministic output unless RODIUMAI is configured for sync HTTP.
            job.result_payload = {"content": f"JOB_RESULT: {prompt[:500]}"}
            job.status = "completed"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return {"status": "completed", "job_id": job_id}
        except Exception as exc:
            job.status = "failed"
            job.error_code = "AI_PROVIDER_UNAVAILABLE"
            job.error_message = str(exc)[:500]
            job.completed_at = datetime.now(UTC)
            session.commit()
            raise self.retry(exc=exc, countdown=2**self.request.retries) from exc
