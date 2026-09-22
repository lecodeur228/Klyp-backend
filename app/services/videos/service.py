"""Video service — upload, fetch, delete with project ownership."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.constants import ErrorCode
from app.core.exceptions import AppException, NotFoundException, ValidationException
from app.models.asset import Asset
from app.models.project import Project
from app.models.video import Video
from app.schemas.video import AssetPublic, VideoPublic
from app.services.jobs import service as jobs_service
from app.services.jobs.service import JOB_TYPE_VIDEO_POST_PROCESS
from app.services.projects import service as projects_service
from app.storage import get_storage
from app.storage.cloudinary_storage import CloudinaryStorage

ALLOWED_VIDEO_TYPES = {
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "video/x-msvideo",
    "video/x-matroska",
}


def to_public(
    video: Video,
    asset: Asset,
    *,
    post_process_job_id: str | None = None,
) -> VideoPublic:
    return VideoPublic(
        id=video.id,
        project_id=video.project_id,
        status=video.status,
        thumbnail_url=video.thumbnail_url,
        original_asset=AssetPublic.model_validate(asset),
        post_process_job_id=post_process_job_id,
        created_at=video.created_at,
        updated_at=video.updated_at,
    )


async def get_owned_video(
    session: AsyncSession,
    *,
    user_id: str,
    video_id: str,
) -> tuple[Video, Asset]:
    result = await session.execute(
        select(Video, Asset)
        .join(Asset, Video.original_asset_id == Asset.id)
        .join(Project, Video.project_id == Project.id)
        .where(Video.id == video_id, Project.user_id == user_id)
    )
    row = result.one_or_none()
    if not row:
        raise NotFoundException("Video not found")
    return row[0], row[1]


async def upload_video(
    session: AsyncSession,
    *,
    user_id: str,
    project_id: str,
    filename: str,
    content: bytes,
    content_type: str,
    settings: Settings,
) -> tuple[Video, Asset, str | None]:
    await projects_service.get_owned_project(
        session, user_id=user_id, project_id=project_id
    )

    if not content:
        raise ValidationException(
            "Empty file",
            errors={"file": ["File is empty"]},
        )
    max_bytes = settings.video_max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise ValidationException(
            "File too large",
            errors={"file": [f"Max size is {settings.video_max_upload_mb}MB"]},
        )
    if content_type not in ALLOWED_VIDEO_TYPES and not content_type.startswith("video/"):
        raise ValidationException(
            "Unsupported file type",
            errors={"file": [f"Type {content_type} not allowed"]},
        )

    storage = get_storage(settings)
    folder = f"projects/{project_id}/originals"
    try:
        upload = await storage.save_media(
            filename=filename,
            content=content,
            content_type=content_type,
            folder=folder,
        )
    except AppException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AppException(
            "Upload failed",
            code=ErrorCode.UPLOAD_FAILED,
            status_code=502,
        ) from exc

    thumbnail_url: str | None = None
    if isinstance(storage, CloudinaryStorage) and upload.resource_type == "video":
        thumbnail_url = storage.video_thumbnail_url(upload.public_id)

    asset = Asset(
        project_id=project_id,
        kind="original",
        filename=filename,
        content_type=content_type,
        public_id=upload.public_id,
        secure_url=upload.secure_url,
        resource_type=upload.resource_type,
        format=upload.format,
        width=upload.width,
        height=upload.height,
        duration=upload.duration,
        size=upload.bytes or len(content),
        metadata_json=upload.metadata or None,
    )
    session.add(asset)
    await session.flush()

    video = Video(
        project_id=project_id,
        original_asset_id=asset.id,
        status="ready",
        thumbnail_url=thumbnail_url,
    )
    session.add(video)
    await session.flush()
    await session.refresh(video)
    await session.refresh(asset)

    job = await jobs_service.create_job(
        session,
        user_id=user_id,
        job_type=JOB_TYPE_VIDEO_POST_PROCESS,
        project_id=project_id,
        video_id=video.id,
        input_payload={"asset_id": asset.id, "filename": filename},
        stage="upload_registered",
    )
    job = await jobs_service.enqueue_post_process(session, job)

    return video, asset, job.id


async def get_video_public(
    session: AsyncSession,
    *,
    user_id: str,
    video_id: str,
) -> VideoPublic:
    video, asset = await get_owned_video(session, user_id=user_id, video_id=video_id)
    post_process_job_id = await jobs_service.get_latest_post_process_job_id(
        session, video_id=video.id
    )
    return to_public(video, asset, post_process_job_id=post_process_job_id)


async def delete_video(
    session: AsyncSession,
    *,
    user_id: str,
    video_id: str,
    settings: Settings,
) -> None:
    video, asset = await get_owned_video(session, user_id=user_id, video_id=video_id)
    storage = get_storage(settings)
    try:
        if isinstance(storage, CloudinaryStorage):
            await storage.delete(asset.public_id, resource_type=asset.resource_type)
        else:
            await storage.delete(asset.secure_url)
    except Exception:  # noqa: BLE001 — DB row still removed; orphan cleanup later
        pass

    await session.delete(video)
    await session.flush()
    await session.delete(asset)
    await session.flush()
