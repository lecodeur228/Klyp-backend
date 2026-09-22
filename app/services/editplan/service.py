"""EditPlan / AI Edit service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompts.registry import render_prompt
from app.ai.providers import build_provider
from app.ai.services import structured_output
from app.core.config import Settings, get_settings
from app.core.constants import ErrorCode
from app.core.exceptions import ConflictException, EditPlanInvalidException, NotFoundException
from app.credits import pricing
from app.editplan.validation import ensure_valid_edit_plan, validate_edit_plan
from app.models.analysis import VideoAnalysis
from app.models.asset import Asset
from app.models.edit_plan import EditPlan
from app.models.job import Job
from app.schemas.editplan import (
    AiEditStarted,
    AudioConfig,
    CaptionsConfig,
    CropOperation,
    EditPlanDocument,
    EditPlanPatchRequest,
    EditPlanPublic,
    EditPlanVersionItem,
    OutputConfig,
    Timeline,
    TimelineSegment,
    ZoomOperation,
)
from app.services.credits import service as credits_service
from app.services.jobs import service as jobs_service
from app.services.projects import service as projects_service
from app.services.videos import service as videos_service

JOB_TYPE_AI_EDIT = "ai_edit"

AI_EDIT_STAGES: list[tuple[str, int]] = [
    ("loading_context", 15),
    ("generating", 50),
    ("validating", 80),
    ("done", 100),
]


def build_fake_edit_plan(
    *,
    source_video_id: str,
    duration: float,
    vad_segments: list[dict[str, Any]] | None = None,
    prompt: str = "",
) -> EditPlanDocument:
    """Deterministic EditPlan for tests / AI_PROVIDER=fake."""
    total = duration if duration and duration > 0 else 30.0
    silences = sorted(
        [
            (float(s["start"]), float(s["end"]))
            for s in (vad_segments or [])
            if s.get("kind", "silence") == "silence"
        ],
        key=lambda x: x[0],
    )

    # Keep ranges = complement of silences within [0, total]
    keeps: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in silences:
        start = max(0.0, min(start, total))
        end = max(0.0, min(end, total))
        if start > cursor + 0.05:
            keeps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < total - 0.05:
        keeps.append((cursor, total))
    if not keeps:
        keeps = [(0.0, total)]

    segments = [
        TimelineSegment(id=f"keep-{i + 1}", start=round(a, 3), end=round(b, 3))
        for i, (a, b) in enumerate(keeps)
        if b > a
    ]

    mid = total / 2
    operations: list[ZoomOperation | CropOperation] = [
        CropOperation(type="crop", aspect_ratio="9:16", mode="smart"),
        ZoomOperation(
            type="zoom",
            start=round(max(0.0, mid - 1.0), 3),
            end=round(min(total, mid + 1.0), 3),
            scale=1.2,
        ),
    ]

    # Prompt hint: if user mentions denoise, enable it
    want_denoise = "denoise" in prompt.lower() or "bruit" in prompt.lower()

    return EditPlanDocument(
        schema_version="1.1.0",
        source_video_id=source_video_id,
        timeline=Timeline(segments=segments),
        operations=operations,
        captions=CaptionsConfig(enabled=True, style="dynamic", theme="prism"),
        visual_style="prism",
        overlays=[],
        audio=AudioConfig(denoise=want_denoise or True, normalize=True),
        output=OutputConfig(resolution="720p", aspect_ratio="9:16"),
    )


def to_public(row: EditPlan) -> EditPlanPublic:
    versions = [
        EditPlanVersionItem(id=f"v{v}", label=f"EditPlan v{v}")
        for v in range(1, row.version + 1)
    ]
    return EditPlanPublic(
        id=row.id,
        project_id=row.project_id,
        source_video_id=row.source_video_id,
        analysis_id=row.analysis_id,
        job_id=row.job_id,
        version=row.version,
        prompt=row.prompt,
        status=row.status,
        plan=dict(row.plan or {}),
        versions=versions,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _get_by_project(
    session: AsyncSession, *, project_id: str
) -> EditPlan | None:
    result = await session.execute(
        select(EditPlan).where(EditPlan.project_id == project_id)
    )
    return result.scalar_one_or_none()


async def get_edit_plan(
    session: AsyncSession,
    *,
    user_id: str,
    project_id: str,
) -> EditPlanPublic:
    await projects_service.get_owned_project(
        session, user_id=user_id, project_id=project_id
    )
    row = await _get_by_project(session, project_id=project_id)
    if not row:
        raise NotFoundException("EditPlan not found")
    return to_public(row)


async def put_edit_plan(
    session: AsyncSession,
    *,
    user_id: str,
    project_id: str,
    document: EditPlanDocument,
) -> EditPlanPublic:
    await projects_service.get_owned_project(
        session, user_id=user_id, project_id=project_id
    )
    row = await _get_by_project(session, project_id=project_id)
    if not row:
        raise NotFoundException("EditPlan not found")

    video, asset = await videos_service.get_owned_video(
        session, user_id=user_id, video_id=row.source_video_id
    )
    duration = float(asset.duration) if asset.duration else 30.0
    document = document.model_copy(update={"source_video_id": video.id})
    validated = validate_edit_plan(document, duration=duration)

    row.plan = validated.model_dump(mode="json")
    row.version = row.version + 1
    row.status = "ready"
    await session.flush()
    await session.refresh(row)
    return to_public(row)


async def patch_edit_plan(
    session: AsyncSession,
    *,
    user_id: str,
    project_id: str,
    patch: EditPlanPatchRequest,
) -> EditPlanPublic:
    await projects_service.get_owned_project(
        session, user_id=user_id, project_id=project_id
    )
    row = await _get_by_project(session, project_id=project_id)
    if not row:
        raise NotFoundException("EditPlan not found")

    current = EditPlanDocument.model_validate(row.plan)
    data = current.model_dump()
    patch_data = patch.model_dump(exclude_unset=True)
    for key, value in patch_data.items():
        if value is not None:
            data[key] = value
    merged = EditPlanDocument.model_validate(data)

    video, asset = await videos_service.get_owned_video(
        session, user_id=user_id, video_id=row.source_video_id
    )
    duration = float(asset.duration) if asset.duration else 30.0
    merged = merged.model_copy(update={"source_video_id": video.id})
    validated = validate_edit_plan(merged, duration=duration)

    row.plan = validated.model_dump(mode="json")
    row.version = row.version + 1
    row.status = "ready"
    await session.flush()
    await session.refresh(row)
    return to_public(row)


async def start_ai_edit(
    session: AsyncSession,
    *,
    user_id: str,
    video_id: str,
    prompt: str,
    settings: Settings | None = None,
) -> AiEditStarted:
    settings = settings or get_settings()
    video, asset = await videos_service.get_owned_video(
        session, user_id=user_id, video_id=video_id
    )

    analysis = (
        await session.execute(
            select(VideoAnalysis).where(VideoAnalysis.video_id == video.id)
        )
    ).scalar_one_or_none()
    if not analysis or analysis.status not in {"ready", "completed"}:
        raise ConflictException("Analysis must be ready before AI Edit")

    amount, _ = pricing.estimate_ai_edit(
        settings, duration_seconds=float(asset.duration) if asset.duration else None
    )
    job_id = str(uuid4())
    await credits_service.require_and_debit(
        session,
        user_id=user_id,
        operation=JOB_TYPE_AI_EDIT,
        amount=amount,
        job_id=job_id,
    )

    row = await _get_by_project(session, project_id=video.project_id)
    if row is None:
        row = EditPlan(
            project_id=video.project_id,
            source_video_id=video.id,
            analysis_id=analysis.id,
            version=0,
            prompt=prompt,
            plan={},
            status="draft",
        )
        session.add(row)
        await session.flush()
    else:
        row.source_video_id = video.id
        row.analysis_id = analysis.id
        row.prompt = prompt
        row.status = "draft"

    job = await jobs_service.create_job(
        session,
        user_id=user_id,
        job_type=JOB_TYPE_AI_EDIT,
        project_id=video.project_id,
        video_id=video.id,
        input_payload={
            "edit_plan_id": row.id,
            "prompt": prompt,
            "analysis_id": analysis.id,
        },
        stage="queued",
        job_id=job_id,
    )
    row.job_id = job.id
    await session.flush()

    await enqueue_ai_edit(
        session,
        job=job,
        edit_plan=row,
        asset=asset,
        analysis=analysis,
        prompt=prompt,
        settings=settings,
    )

    return AiEditStarted(
        job_id=job.id,
        edit_plan_id=row.id,
        status=row.status,
    )


async def generate_edit_plan_document(
    session: AsyncSession,
    *,
    user_id: str,
    video_id: str,
    prompt: str,
    duration: float,
    analysis: VideoAnalysis,
    settings: Settings,
) -> EditPlanDocument:
    if settings.ai_provider == "fake" or settings.app_env == "test":
        return ensure_valid_edit_plan(
            build_fake_edit_plan(
                source_video_id=video_id,
                duration=duration,
                vad_segments=list(analysis.vad_segments or []),
                prompt=prompt,
            ),
            duration=duration,
        )

    def _fallback() -> EditPlanDocument:
        return ensure_valid_edit_plan(
            build_fake_edit_plan(
                source_video_id=video_id,
                duration=duration,
                vad_segments=list(analysis.vad_segments or []),
                prompt=prompt,
            ),
            duration=duration,
        )

    provider = build_provider(settings)
    transcript_preview = ""
    for seg in (analysis.segments or [])[:5]:
        transcript_preview += f"- {seg.get('text', '')}\n"
    vad_preview = str(analysis.vad_segments or [])[:500]
    system, user_msg, _version = render_prompt(
        "edit_plan",
        prompt=prompt,
        duration=str(duration),
        transcript=transcript_preview or "(empty)",
        vad=vad_preview,
        source_video_id=video_id,
    )
    schema = EditPlanDocument.model_json_schema()
    try:
        result = await structured_output.generate_structured(
            provider,
            session,
            user_id=user_id,
            prompt=user_msg,
            system=system,
            schema=schema,
        )
        document = EditPlanDocument.model_validate(result.data)
        document = document.model_copy(update={"source_video_id": video_id})
        return ensure_valid_edit_plan(document, duration=duration)
    except Exception:  # noqa: BLE001
        # Noisy AI output must not break vibe editing — heal with heuristic plan
        return _fallback()


async def complete_ai_edit_inline(
    session: AsyncSession,
    *,
    job: Job,
    edit_plan: EditPlan,
    asset: Asset,
    analysis: VideoAnalysis,
    prompt: str,
    settings: Settings,
    user_id: str,
) -> EditPlan:
    if job.status == "cancelled":
        edit_plan.status = "failed"
        await credits_service.refund_job(session, job_id=job.id)
        await session.flush()
        return edit_plan

    job.status = "processing"
    job.started_at = datetime.now(UTC)
    edit_plan.status = "draft"

    for stage, progress in AI_EDIT_STAGES[:-1]:
        job.stage = stage
        job.progress = progress

    duration = float(asset.duration) if asset.duration else 30.0
    try:
        document = await generate_edit_plan_document(
            session,
            user_id=user_id,
            video_id=edit_plan.source_video_id,
            prompt=prompt,
            duration=duration,
            analysis=analysis,
            settings=settings,
        )
        validated = ensure_valid_edit_plan(document, duration=duration)
        edit_plan.plan = validated.model_dump(mode="json")
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
    except EditPlanInvalidException as exc:
        edit_plan.status = "failed"
        job.status = "failed"
        job.error_code = ErrorCode.EDIT_PLAN_INVALID.value
        job.error_message = exc.message
        job.completed_at = datetime.now(UTC)
        await credits_service.refund_job(session, job_id=job.id)
        raise
    except Exception as exc:  # noqa: BLE001
        edit_plan.status = "failed"
        job.status = "failed"
        job.error_code = ErrorCode.JOB_FAILED.value
        job.error_message = str(exc)[:500]
        job.completed_at = datetime.now(UTC)
        await credits_service.refund_job(session, job_id=job.id)
        raise

    await session.flush()
    await session.refresh(edit_plan)
    await session.refresh(job)
    return edit_plan


async def enqueue_ai_edit(
    session: AsyncSession,
    *,
    job: Job,
    edit_plan: EditPlan,
    asset: Asset,
    analysis: VideoAnalysis,
    prompt: str,
    settings: Settings,
) -> Job:
    if settings.app_env == "test":
        await complete_ai_edit_inline(
            session,
            job=job,
            edit_plan=edit_plan,
            asset=asset,
            analysis=analysis,
            prompt=prompt,
            settings=settings,
            user_id=job.user_id,
        )
        return job

    from app.workers.tasks.ai_edit import run_ai_edit_job

    try:
        async_result = run_ai_edit_job.delay(job.id)
        job.celery_task_id = str(async_result.id)
        edit_plan.status = "draft"
        await session.flush()
        await session.refresh(job)
        return job
    except Exception:  # noqa: BLE001
        await complete_ai_edit_inline(
            session,
            job=job,
            edit_plan=edit_plan,
            asset=asset,
            analysis=analysis,
            prompt=prompt,
            settings=settings,
            user_id=job.user_id,
        )
        return job
