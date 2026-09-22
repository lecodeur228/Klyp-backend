"""Video analysis Celery tasks."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.analysis.providers import get_transcription_provider
from app.core.config import get_settings
from app.core.constants import ErrorCode
from app.models.analysis import VideoAnalysis
from app.models.asset import Asset
from app.models.job import Job
from app.models.video import Video
from app.services.analysis.service import ANALYZE_STAGES, _segments_to_json
from app.workers.celery_app import celery_app

settings = get_settings()
sync_engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
SyncSession = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)


@celery_app.task(name="app.workers.tasks.analysis.analyze_video_job", bind=True, max_retries=2)
def analyze_video_job(self, job_id: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    with SyncSession() as session:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
        if not job:
            return {"status": "missing"}
        if job.status == "cancelled":
            return {"status": "cancelled", "job_id": job_id}

        analysis = session.execute(
            select(VideoAnalysis).where(VideoAnalysis.job_id == job_id)
        ).scalar_one_or_none()
        if not analysis and job.video_id:
            analysis = session.execute(
                select(VideoAnalysis).where(VideoAnalysis.video_id == job.video_id)
            ).scalar_one_or_none()

        video = None
        asset = None
        if job.video_id:
            video = session.execute(
                select(Video).where(Video.id == job.video_id)
            ).scalar_one_or_none()
        if video:
            asset = session.execute(
                select(Asset).where(Asset.id == video.original_asset_id)
            ).scalar_one_or_none()

        job.celery_task_id = self.request.id
        job.status = "processing"
        job.started_at = datetime.now(UTC)
        if analysis:
            analysis.status = "processing"
            analysis.job_id = job.id
        session.commit()

        try:
            for stage, progress in ANALYZE_STAGES[:-1]:
                session.refresh(job)
                if job.status == "cancelled":
                    return {"status": "cancelled", "job_id": job_id}
                job.stage = stage
                job.progress = progress
                session.commit()

            if not analysis or not asset:
                raise RuntimeError("Analysis or asset missing")

            provider = get_transcription_provider(settings)
            duration = float(asset.duration) if asset.duration else 0.0
            result = provider.transcribe(
                duration=duration,
                language="fr",
                media_url=asset.secure_url,
            )

            analysis.language = result.language
            analysis.segments = _segments_to_json(result)
            analysis.vad_segments = list(result.vad_segments)
            analysis.fillers = list(result.fillers)
            analysis.scenes = []
            analysis.faces = []
            analysis.quality_warning = getattr(result, "quality_warning", None)
            analysis.aligned = bool(getattr(result, "aligned", False))
            analysis.status = "ready"
            analysis.error_code = None
            analysis.error_message = None

            job.stage = "done"
            job.progress = 100
            job.status = "completed"
            job.result_payload = {
                "analysis_id": analysis.id,
                "segment_count": len(analysis.segments or []),
            }
            job.completed_at = datetime.now(UTC)
            session.commit()
            return {"status": "completed", "job_id": job_id}
        except Exception as exc:
            if analysis:
                analysis.status = "failed"
                analysis.error_code = ErrorCode.JOB_FAILED.value
                analysis.error_message = str(exc)[:500]
            job.status = "failed"
            job.error_code = ErrorCode.JOB_FAILED.value
            job.error_message = str(exc)[:500]
            job.completed_at = datetime.now(UTC)
            session.commit()
            raise self.retry(exc=exc, countdown=2**self.request.retries) from exc
