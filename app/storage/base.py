"""Storage abstraction."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Protocol

import aiofiles
import aiofiles.os

from app.core.config import Settings
from app.core.constants import ErrorCode
from app.core.exceptions import AppException
from app.storage.types import UploadResult


class StorageBackend(Protocol):
    async def save(self, *, filename: str, content: bytes, content_type: str) -> str: ...

    async def save_media(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str,
        folder: str | None = None,
    ) -> UploadResult: ...

    async def delete(self, path: str) -> None: ...


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

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
        safe_name = Path(filename).name
        key = f"{uuid.uuid4().hex}_{safe_name}"
        relative = f"{folder.strip('/')}/{key}" if folder else key
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(target, "wb") as handle:
            await handle.write(content)
        suffix = Path(filename).suffix.lstrip(".") or None
        resource_type = "video" if content_type.startswith(("video/", "audio/")) else (
            "image" if content_type.startswith("image/") else "raw"
        )
        return UploadResult(
            public_id=relative,
            secure_url=str(target),
            resource_type=resource_type,
            format=suffix,
            bytes=len(content),
            metadata={"backend": "local"},
        )

    async def delete(self, path: str) -> None:
        try:
            await aiofiles.os.remove(path)
        except FileNotFoundError:
            return None


class S3StorageStub:
    """Stub — not used at launch (PRD: Cloudinary only)."""

    def __init__(self, settings: Settings) -> None:
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
        folder_part = f"{folder.strip('/')}/" if folder else ""
        public_id = f"{folder_part}{uuid.uuid4().hex}_{Path(filename).stem}"
        key = f"s3://{self.settings.s3_bucket}/{public_id}"
        return UploadResult(
            public_id=public_id,
            secure_url=key,
            resource_type="video",
            format=Path(filename).suffix.lstrip(".") or None,
            bytes=len(content),
            metadata={"backend": "s3-stub"},
        )

    async def delete(self, path: str) -> None:
        return None


def get_storage(settings: Settings) -> StorageBackend:
    if settings.storage_backend == "cloudinary":
        if not settings.cloudinary_configured:
            raise AppException(
                "STORAGE_BACKEND=cloudinary but Cloudinary credentials are missing",
                code=ErrorCode.SERVER_ERROR,
                status_code=500,
            )
        from app.storage.cloudinary_storage import CloudinaryStorage

        return CloudinaryStorage(settings)
    if settings.storage_backend == "s3":
        return S3StorageStub(settings)
    return LocalStorage(settings.storage_local_path)
