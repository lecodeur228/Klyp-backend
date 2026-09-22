"""Analysis service — start, get, complete via job."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.providers import get_transcription_provider
from app.analysis.providers.base import TranscriptResult
from app.core.config import Settings, get_settings
from app.core.constants import ErrorCode
from app.core.exceptions import ConflictException, NotFoundException
from app.credits import pricing
from app.models.analysis import VideoAnalysis
from app.models.asset import Asset
from app.models.job import Job
from app.pipeline.transcription.qa_check import evaluate_sync_qa
from app.schemas.analysis import AnalysisPublic, AnalysisStarted
from app.services.credits import service as credits_service
from app.services.jobs import service as jobs_service
from app.services.projects import service as projects_service
from app.services.videos import service as videos_service

JOB_TYPE_VIDEO_ANALYZE = "video.analyze"

ANALYZE_STAGES: list[tuple[str, int]] = [
    ("probing", 10),
    ("transcribing", 40),
    ("vad", 70),
    ("done", 100),
]


def _segments_to_json(result: TranscriptResult) -> list[dict[str, Any]]:
    return [
        {
            "id": seg.id,
            "start": seg.start,
            "end": seg.end,
            "text": seg.text,
            "words": [
                {"word": w.word, "start": w.start, "end": w.end} for w in seg.words
            ],
        }
        for seg in result.segments
    ]


def to_public(analysis: VideoAnalysis) -> AnalysisPublic:
    qa = evaluate_sync_qa(
        vad_segments=list(analysis.vad_segments or []),
        segments=list(analysis.segments or []),
        aligned=bool(getattr(analysis, "aligned", False)),
        quality_warning=analysis.quality_warning,
    )
    return AnalysisPublic(
        id=analysis.id,
        video_id=analysis.video_id,
        job_id=analysis.job_id,
        status=analysis.status,
        language=analysis.language,
        segments=list(analysis.segments or []),
        vad_segments=list(analysis.vad_segments or []),
        fillers=list(analysis.fillers or []),
        scenes=list(analysis.scenes or []),
        faces=list(analysis.faces or []),
        quality_warning=analysis.quality_warning,
        aligned=bool(getattr(analysis, "aligned", False)),
        needs_review=bool(qa.get("needs_review")),
        qa_metrics=qa,
        error_code=analysis.error_code,
        error_message=analysis.error_message,
        created_at=analysis.created_at,
        updated_at=analysis.updated_at,
    )


async def _get_analysis_by_video(
    session: AsyncSession, *, video_id: str
) -> VideoAnalysis | None:
    result = await session.execute(
        select(VideoAnalysis).where(VideoAnalysis.video_id == video_id)
    )
    return result.scalar_one_or_none()


async def get_analysis(
    session: AsyncSession,
    *,
    user_id: str,
    video_id: str,
) -> AnalysisPublic:
    await videos_service.get_owned_video(session, user_id=user_id, video_id=video_id)
    analysis = await _get_analysis_by_video(session, video_id=video_id)
    if not analysis:
        raise NotFoundException("Analysis not found")
    return to_public(analysis)


async def start_analysis(
    session: AsyncSession,
    *,
    user_id: str,
    video_id: str,
    settings: Settings | None = None,
) -> AnalysisStarted:
    settings = settings or get_settings()
    video, asset = await videos_service.get_owned_video(
        session, user_id=user_id, video_id=video_id
    )

    analysis = await _get_analysis_by_video(session, video_id=video.id)
    if analysis and analysis.status == "processing":
        raise ConflictException("Analysis already in progress")

    amount, _ = pricing.estimate_analyze(
        settings, duration_seconds=float(asset.duration) if asset.duration else None
    )
    job_id = str(uuid4())
    await credits_service.require_and_debit(
        session,
        user_id=user_id,
        operation=JOB_TYPE_VIDEO_ANALYZE,
        amount=amount,
        job_id=job_id,
    )

    # Re-read after debit — avoid stale None when a row already exists
    analysis = await _get_analysis_by_video(session, video_id=video.id)

    if analysis is None:
        # One row per video — race-safe create (UNIQUE video_id)
        try:
            async with session.begin_nested():
                analysis = VideoAnalysis(
                    video_id=video.id,
                    status="pending",
                    segments=[],
                    vad_segments=[],
                    fillers=[],
                    scenes=[],
                    faces=[],
                )
                session.add(analysis)
                await session.flush()
        except IntegrityError:
            analysis = await _get_analysis_by_video(session, video_id=video.id)
            if analysis is None:
                raise

    job = await jobs_service.create_job(
        session,
        user_id=user_id,
        job_type=JOB_TYPE_VIDEO_ANALYZE,
        project_id=video.project_id,
        video_id=video.id,
        input_payload={"analysis_id": analysis.id, "asset_id": asset.id},
        stage="queued",
        job_id=job_id,
    )

    analysis.job_id = job.id
    analysis.status = "pending"
    analysis.language = None
    analysis.segments = []
    analysis.vad_segments = []
    analysis.fillers = []
    analysis.scenes = []
    analysis.faces = []
    analysis.quality_warning = None
    analysis.aligned = False
    analysis.error_code = None
    analysis.error_message = None
    await session.flush()

    await enqueue_analysis(session, job=job, analysis=analysis, asset=asset, settings=settings)

    return AnalysisStarted(
        analysis_id=analysis.id,
        job_id=job.id,
        status=analysis.status,
    )


async def complete_analysis_inline(
    session: AsyncSession,
    *,
    job: Job,
    analysis: VideoAnalysis,
    asset: Asset,
    settings: Settings,
) -> VideoAnalysis:
    if job.status == "cancelled":
        analysis.status = "failed"
        analysis.error_code = ErrorCode.JOB_FAILED.value
        analysis.error_message = "Job cancelled"
        await credits_service.refund_job(session, job_id=job.id)
        await session.flush()
        return analysis

    job.status = "processing"
    job.started_at = datetime.now(UTC)
    analysis.status = "processing"

    for stage, progress in ANALYZE_STAGES[:-1]:
        job.stage = stage
        job.progress = progress

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
    analysis.aligned = bool(result.aligned)
    qa = evaluate_sync_qa(
        vad_segments=analysis.vad_segments,
        segments=analysis.segments,
        aligned=analysis.aligned,
        quality_warning=result.quality_warning,
    )
    if qa.get("needs_review") and not result.quality_warning:
        analysis.quality_warning = (
            f"needs_review: sync drift {qa.get('drift_s')}s "
            f"(vad={qa.get('vad_speech_s')}s words={qa.get('word_coverage_s')}s)"
        )
    else:
        analysis.quality_warning = result.quality_warning
    analysis.status = "ready"
    analysis.error_code = None
    analysis.error_message = None

    job.stage = "done"
    job.progress = 100
    job.status = "completed"
    job.result_payload = {
        "analysis_id": analysis.id,
        "segment_count": len(analysis.segments or []),
        "qa": qa,
        "needs_review": bool(qa.get("needs_review")),
    }
    job.completed_at = datetime.now(UTC)

    renamed = await projects_service.maybe_rename_from_transcript(
        session,
        video_id=analysis.video_id,
        segments=analysis.segments,
    )
    if renamed:
        job.result_payload = {
            **(job.result_payload or {}),
            "project_title": renamed,
        }

    await session.flush()
    await session.refresh(analysis)
    await session.refresh(job)

    # Creative plan runs separately via POST /creative-plan (editor pipeline)
    # so analyze stays ASR-only and can return without waiting on gpt-4o.

    return analysis


async def enqueue_analysis(
    session: AsyncSession,
    *,
    job: Job,
    analysis: VideoAnalysis,
    asset: Asset,
    settings: Settings,
) -> Job:
    # Prefer inline ASR in local/dev so transcripts don't depend on Celery workers.
    if settings.app_env in {"test", "development"}:
        await complete_analysis_inline(
            session, job=job, analysis=analysis, asset=asset, settings=settings
        )
        return job

    from app.workers.tasks.analysis import analyze_video_job

    try:
        async_result = analyze_video_job.delay(job.id)
        job.celery_task_id = str(async_result.id)
        analysis.status = "processing"
        await session.flush()
        await session.refresh(job)
        return job
    except Exception:  # noqa: BLE001
        await complete_analysis_inline(
            session, job=job, analysis=analysis, asset=asset, settings=settings
        )
        return job
