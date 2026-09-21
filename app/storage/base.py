"""Storage abstraction."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Protocol

import aiofiles
import aiofiles.os

from app.core.config import Settings


class StorageBackend(Protocol):
    async def save(self, *, filename: str, content: bytes, content_type: str) -> str: ...

    async def delete(self, path: str) -> None: ...


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    async def save(self, *, filename: str, content: bytes, content_type: str) -> str:
        safe_name = Path(filename).name
        key = f"{uuid.uuid4().hex}_{safe_name}"
        target = self.root / key
        async with aiofiles.open(target, "wb") as handle:
            await handle.write(content)
        return str(target)

    async def delete(self, path: str) -> None:
        try:
            await aiofiles.os.remove(path)
        except FileNotFoundError:
            return None


class S3StorageStub:
    """V1 stub — replace with real boto3 client in production."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def save(self, *, filename: str, content: bytes, content_type: str) -> str:
        key = f"s3://{self.settings.s3_bucket}/{uuid.uuid4().hex}_{Path(filename).name}"
        return key

    async def delete(self, path: str) -> None:
        return None


def get_storage(settings: Settings) -> StorageBackend:
    if settings.storage_backend == "s3":
        return S3StorageStub(settings)
    return LocalStorage(settings.storage_local_path)
