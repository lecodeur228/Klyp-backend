"""Cloudinary storage backend."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import cloudinary
import cloudinary.uploader
from cloudinary.utils import cloudinary_url

from app.core.config import Settings
from app.core.constants import ErrorCode
from app.core.exceptions import AppException
from app.storage.types import UploadResult


class CloudinaryStorage:
    """Upload / delete media via Cloudinary (source of truth for binaries)."""

    def __init__(self, settings: Settings) -> None:
        if not settings.cloudinary_configured:
            raise AppException(
                "Cloudinary is not configured",
                code=ErrorCode.SERVER_ERROR,
                status_code=500,
            )
        cloudinary.config(
            cloud_name=settings.cloudinary_cloud_name,
            api_key=settings.cloudinary_api_key,
            api_secret=settings.cloudinary_api_secret,
            secure=True,
        )
        self.settings = settings

    async def save(self, *, filename: str, content: bytes, content_type: str) -> str:
        result = await self.save_media(
            filename=filename, content=content, content_type=content_type
        )
        return result.secure_url

    async def save_media(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str,
        folder: str | None = None,
    ) -> UploadResult:
        safe_name = Path(filename).stem
        folder_prefix = folder.strip("/") if folder else "klyp/uploads"
        public_id = f"{folder_prefix}/{uuid.uuid4().hex}_{safe_name}"
        resource_type = _resource_type(content_type)

        def _upload() -> dict:
            return cloudinary.uploader.upload(
                content,
                public_id=public_id,
                resource_type=resource_type,
                overwrite=False,
            )

        try:
            raw = await asyncio.to_thread(_upload)
        except Exception as exc:  # noqa: BLE001 — map SDK errors to domain
            raise AppException(
                "Upload to Cloudinary failed",
                code=ErrorCode.UPLOAD_FAILED,
                status_code=502,
            ) from exc

        return UploadResult(
            public_id=str(raw.get("public_id") or public_id),
            secure_url=str(raw.get("secure_url") or raw.get("url") or ""),
            resource_type=str(raw.get("resource_type") or resource_type),
            format=raw.get("format"),
            width=_as_int(raw.get("width")),
            height=_as_int(raw.get("height")),
            duration=_as_float(raw.get("duration")),
            bytes=_as_int(raw.get("bytes")) or len(content),
            metadata={
                k: raw[k]
                for k in ("version", "etag", "bit_rate", "frame_rate", "nb_frames")
                if k in raw
            },
        )

    async def delete(self, path: str, *, resource_type: str = "image") -> None:
        """`path` may be a public_id or a full Cloudinary URL."""
        public_id = _public_id_from_path(path)

        def _destroy() -> None:
            cloudinary.uploader.destroy(
                public_id, invalidate=True, resource_type=resource_type
            )

        await asyncio.to_thread(_destroy)

    def optimized_url(self, public_id: str, **options: object) -> str:
        url, _ = cloudinary_url(
            public_id,
            fetch_format=options.pop("fetch_format", "auto"),
            quality=options.pop("quality", "auto"),
            **options,
        )
        return str(url)

    def video_thumbnail_url(self, public_id: str, *, second: float = 0.0) -> str:
        """First-frame (or so_N) JPEG derived from the video — no extra upload."""
        url, _ = cloudinary_url(
            public_id,
            resource_type="video",
            format="jpg",
            start_offset=second,
            width=640,
            crop="limit",
        )
        return str(url)


def _resource_type(content_type: str) -> str:
    if content_type.startswith("video/"):
        return "video"
    if content_type.startswith("audio/"):
        return "video"  # Cloudinary stores audio under video resource type
    if content_type.startswith("image/"):
        return "image"
    return "raw"


def _public_id_from_path(path: str) -> str:
    if "res.cloudinary.com" not in path:
        return path
    # …/upload/v123/folder/name.ext → folder/name
    parts = path.split("/upload/")
    if len(parts) < 2:
        return path
    rest = parts[1]
    # drop version segment v123/
    segments = rest.split("/")
    if segments and segments[0].startswith("v") and segments[0][1:].isdigit():
        segments = segments[1:]
    joined = "/".join(segments)
    return Path(joined).with_suffix("").as_posix()


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def configure_cloudinary(settings: Settings) -> None:
    """Apply Cloudinary SDK config from settings (for services / workers)."""
    if not settings.cloudinary_configured:
        return
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True,
    )
