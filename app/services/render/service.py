"""Render service — EditPlan → FFmpeg (or stub) → Asset."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.constants import ErrorCode
from app.core.exceptions import AppException, ConflictException, NotFoundException
from app.credits import pricing
from app.editplan.validation import validate_edit_plan
from app.models.asset import Asset
from app.models.edit_plan import EditPlan
from app.models.job import Job
from app.models.render import Render
from app.render.ffmpeg import run_ffmpeg_or_stub
from app.schemas.editplan import EditPlanDocument
from app.schemas.render import RenderPublic, RenderStarted
from app.services.credits import service as credits_service
from app.services.jobs import service as jobs_service
from app.services.projects import service as projects_service
from app.services.videos import service as videos_service
from app.storage import get_storage

JOB_TYPE_PROJECT_RENDER = "project.render"
RenderKind = Literal["preview", "export"]

RENDER_STAGES: list[tuple[str, int]] = [
    ("loading", 15),
    ("rendering", 55),
    ("uploading", 85),
    ("done", 100),
]


def to_public(row: Render) -> RenderPublic:
    return RenderPublic(
        id=row.id,
        project_id=row.project_id,
        user_id=row.user_id,
        edit_plan_id=row.edit_plan_id,
        source_video_id=row.source_video_id,
        job_id=row.job_id,
        output_asset_id=row.output_asset_id,
        status=row.status,
        kind=row.kind,
        secure_url=row.secure_url,
        error_code=row.error_code,
        error_message=row.error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def get_owned_render(
    session: AsyncSession,
    *,
    user_id: str,
    render_id: str,
) -> Render:
    result = await session.execute(
        select(Render).where(Render.id == render_id, Render.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise NotFoundException("Render not found")
    return row


async def get_render_public(
    session: AsyncSession,
    *,
    user_id: str,
    render_id: str,
) -> RenderPublic:
    return to_public(await get_owned_render(session, user_id=user_id, render_id=render_id))


async def start_render(
    session: AsyncSession,
    *,
    user_id: str,
    project_id: str,
    kind: RenderKind = "export",
    settings: Settings | None = None,
) -> RenderStarted:
    settings = settings or get_settings()
    await projects_service.get_owned_project(
        session, user_id=user_id, project_id=project_id
    )

    edit_plan = (
        await session.execute(select(EditPlan).where(EditPlan.project_id == project_id))
    ).scalar_one_or_none()
    if not edit_plan or edit_plan.status not in {"ready", "validated"}:
        raise ConflictException("EditPlan must be ready before render")

    document = EditPlanDocument.model_validate(edit_plan.plan)
    video, asset = await videos_service.get_owned_video(
        session, user_id=user_id, video_id=edit_plan.source_video_id
    )
    duration = float(asset.duration) if asset.duration else 30.0
    validate_edit_plan(document, duration=duration)

    # Conflict if another render for this plan is processing
    active = (
        await session.execute(
            select(Render).where(
                Render.project_id == project_id,
                Render.status == "processing",
            )
        )
    ).scalar_one_or_none()
    if active:
        raise ConflictException("A render is already in progress")

    amount, _ = pricing.estimate_render(
        settings,
        duration_seconds=duration,
        kind=kind,
    )
    job_id = str(uuid4())
    await credits_service.require_and_debit(
        session,
        user_id=user_id,
        operation=JOB_TYPE_PROJECT_RENDER,
        amount=amount,
        job_id=job_id,
    )

    row = Render(
        project_id=project_id,
        user_id=user_id,
        edit_plan_id=edit_plan.id,
        source_video_id=video.id,
        status="pending",
        kind=kind,
    )
    session.add(row)
    await session.flush()

    job = await jobs_service.create_job(
        session,
        user_id=user_id,
        job_type=JOB_TYPE_PROJECT_RENDER,
        project_id=project_id,
        video_id=video.id,
        input_payload={
            "render_id": row.id,
            "edit_plan_id": edit_plan.id,
            "kind": kind,
        },
        stage="queued",
        job_id=job_id,
    )
    row.job_id = job.id
    await session.flush()

    await enqueue_render(
        session,
        job=job,
        render=row,
        edit_plan=edit_plan,
        source_asset=asset,
        settings=settings,
    )

    return RenderStarted(render_id=row.id, job_id=job.id, status=row.status)


async def complete_render_inline(
    session: AsyncSession,
    *,
    job: Job,
    render: Render,
    edit_plan: EditPlan,
    source_asset: Asset,
    settings: Settings,
) -> Render:
    if job.status == "cancelled":
        render.status = "failed"
        render.error_code = ErrorCode.JOB_FAILED.value
        render.error_message = "Job cancelled"
        await credits_service.refund_job(session, job_id=job.id)
        await session.flush()
        return render

    job.status = "processing"
    job.started_at = datetime.now(UTC)
    render.status = "processing"

    for stage, progress in RENDER_STAGES[:-1]:
        job.stage = stage
        job.progress = progress

    try:
        from app.captions.build import build_cues
        from app.models.analysis import VideoAnalysis
        from app.render.ass import build_ass_from_cues
        from app.render.ffmpeg import remap_cues_to_output, remap_overlays_to_output
        from app.services.creative.cuts import keep_tuples

        document = EditPlanDocument.model_validate(edit_plan.plan)
        work_dir = Path(f"/tmp/jobs/{job.id}")
        output_path = work_dir / "output.mp4"
        local_source = work_dir / "source.mp4"
        ass_path = work_dir / "captions.ass"

        analysis = (
            await session.execute(
                select(VideoAnalysis).where(
                    VideoAnalysis.video_id == edit_plan.source_video_id
                )
            )
        ).scalar_one_or_none()
        cues = build_cues(
            list(analysis.segments or []) if analysis else [],
            style=document.captions.style,
        )
        keeps = keep_tuples(document.timeline.segments)
        cues_out = remap_cues_to_output(cues, keeps) if keeps else cues

        def _prepare_and_render() -> object:
            import httpx

            work_dir.mkdir(parents=True, exist_ok=True)

            source_url = source_asset.secure_url
            if source_url.startswith("http"):
                with httpx.Client(timeout=180.0, follow_redirects=True) as client:
                    resp = client.get(source_url)
                    resp.raise_for_status()
                    local_source.write_bytes(resp.content)
                input_path = local_source
            else:
                input_path = Path(source_url)

            if document.captions.enabled and cues_out:
                build_ass_from_cues(plan=document, cues=cues_out, output_path=ass_path)

            overlay_inputs: list[tuple[Path, float, float, str]] = []
            for i, ov in enumerate(document.overlays):
                if ov.status not in {"ready", "accepted"} or not ov.asset_url:
                    continue
                ov_path = work_dir / f"overlay-{i}.png"
                layout = getattr(ov, "layout", None) or (
                    "cover" if ov.kind == "background" else "plate"
                )
                if ov.asset_url.startswith("http"):
                    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
                        img = client.get(ov.asset_url)
                        if img.status_code < 400:
                            ov_path.write_bytes(img.content)
                            overlay_inputs.append(
                                (ov_path, float(ov.start), float(ov.end), str(layout))
                            )
                elif Path(ov.asset_url).exists():
                    overlay_inputs.append(
                        (
                            Path(ov.asset_url),
                            float(ov.start),
                            float(ov.end),
                            str(layout),
                        )
                    )

            overlay_out = (
                remap_overlays_to_output(overlay_inputs, keeps)
                if keeps
                else overlay_inputs
            )

            exists = input_path.exists()
            force = settings.app_env == "test" or not exists
            return run_ffmpeg_or_stub(
                input_path=input_path if exists else None,
                output_path=output_path,
                plan=document,
                force_stub=force,
                source_bytes=None,
                ass_path=ass_path if ass_path.exists() else None,
                overlay_inputs=overlay_out or None,
            )

        import asyncio

        result = await asyncio.to_thread(_prepare_and_render)
        content = await asyncio.to_thread(result.output_path.read_bytes)  # type: ignore[union-attr]
        storage = get_storage(settings)
        folder = f"projects/{render.project_id}/renders"
        upload = await storage.save_media(
            filename=f"render-{render.id}.mp4",
            content=content,
            content_type="video/mp4",
            folder=folder,
        )

        out_asset = Asset(
            project_id=render.project_id,
            kind="render",
            filename=f"render-{render.id}.mp4",
            content_type="video/mp4",
            public_id=upload.public_id,
            secure_url=upload.secure_url,
            resource_type="video",
            format="mp4",
            width=result.width,
            height=result.height,
            size=len(content),
            metadata_json={"stub": result.stub, "kind": render.kind},
        )
        session.add(out_asset)
        await session.flush()

        render.output_asset_id = out_asset.id
        render.secure_url = out_asset.secure_url
        render.status = "ready"
        render.error_code = None
        render.error_message = None
        render.job_id = job.id

        job.stage = "done"
        job.progress = 100
        job.status = "completed"
        job.result_payload = {
            "render_id": render.id,
            "secure_url": render.secure_url,
            "stub": result.stub,
        }
        job.completed_at = datetime.now(UTC)
    except AppException as exc:
        render.status = "failed"
        render.error_code = exc.code.value
        render.error_message = exc.message
        job.status = "failed"
        job.error_code = exc.code.value
        job.error_message = exc.message
        job.completed_at = datetime.now(UTC)
        await credits_service.refund_job(session, job_id=job.id)
        raise
    except Exception as exc:  # noqa: BLE001
        render.status = "failed"
        render.error_code = ErrorCode.RENDER_FAILED.value
        render.error_message = str(exc)[:500]
        job.status = "failed"
        job.error_code = ErrorCode.RENDER_FAILED.value
        job.error_message = str(exc)[:500]
        job.completed_at = datetime.now(UTC)
        await credits_service.refund_job(session, job_id=job.id)
        raise AppException(
            str(exc)[:500],
            code=ErrorCode.RENDER_FAILED,
            status_code=502,
        ) from exc
    finally:
        # Best-effort cleanup of temp dir
        try:
            import shutil

            shutil.rmtree(f"/tmp/jobs/{job.id}", ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass

    await session.flush()
    await session.refresh(render)
    await session.refresh(job)
    return render


async def enqueue_render(
    session: AsyncSession,
    *,
    job: Job,
    render: Render,
    edit_plan: EditPlan,
    source_asset: Asset,
    settings: Settings,
) -> Job:
    if settings.app_env in {"test", "development"}:
        await complete_render_inline(
            session,
            job=job,
            render=render,
            edit_plan=edit_plan,
            source_asset=source_asset,
            settings=settings,
        )
        return job

    from app.workers.tasks.render import run_render_job

    try:
        async_result = run_render_job.delay(job.id)
        job.celery_task_id = str(async_result.id)
        render.status = "processing"
        await session.flush()
        await session.refresh(job)
        return job
    except Exception:  # noqa: BLE001
        await complete_render_inline(
            session,
            job=job,
            render=render,
            edit_plan=edit_plan,
            source_asset=source_asset,
            settings=settings,
        )
        return job
